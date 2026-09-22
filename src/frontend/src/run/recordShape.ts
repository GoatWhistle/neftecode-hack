/**
 * Структурная проверка записи прогона на границе импорта.
 *
 * Проверяются поля, которые читают восстановление, сравнение пары и экран результата.
 * Обязательное поле, пришедшее как null/undefined/другой тип, — ошибка; поле, которое сервер
 * законно не передаёт, объявлено opt/nullable и остаётся честным отсутствием. Недостающие
 * значения не дополняются. Лишние ключи не проверяются: экспорт и так пропускает их по списку.
 */

export class ShapeError extends Error {
  constructor(readonly path: string, readonly expected: string) {
    super(`${path}: ожидалось ${expected}`);
  }
}

export type Check = (value: unknown, path: string) => void;

const fail = (path: string, expected: string): never => {
  throw new ShapeError(path, expected);
};

export const str: Check = (v, p) => { if (typeof v !== "string") fail(p, "строка"); };
export const num: Check = (v, p) => { if (typeof v !== "number" || !Number.isFinite(v)) fail(p, "конечное число"); };
export const bool: Check = (v, p) => { if (typeof v !== "boolean") fail(p, "логическое значение"); };
export const any: Check = (v, p) => { if (v === undefined) fail(p, "значение"); };

export const oneOf = (...values: readonly string[]): Check => (v, p) => {
  if (typeof v !== "string" || !values.includes(v)) fail(p, `одно из: ${values.join(", ")}`);
};

/** Ключ обязан присутствовать; null допустим как явное «неизвестно». */
export const nullable = (check: Check): Check => (v, p) => { if (v !== null) check(v, p); };

/** Ключ может отсутствовать (старые или частичные ответы сервера). */
export const opt = (check: Check): Check => (v, p) => { if (v !== undefined) check(v, p); };

export const optNull = (check: Check): Check => opt(nullable(check));

export const either = (...checks: Check[]): Check => (v, p) => {
  const errors: ShapeError[] = [];
  for (const check of checks) {
    try {
      check(v, p);
      return;
    } catch (error) {
      if (!(error instanceof ShapeError)) throw error;
      errors.push(error);
    }
  }
  fail(p, errors.map((e) => e.expected).join(" или "));
};

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export const arr = (item: Check): Check => (v, p) => {
  if (!Array.isArray(v)) fail(p, "массив");
  (v as unknown[]).forEach((x, i) => item(x, `${p}[${i}]`));
};

export const dict = (item: Check): Check => (v, p) => {
  if (!isPlainObject(v)) fail(p, "объект");
  for (const [k, x] of Object.entries(v as Record<string, unknown>)) item(x, `${p}.${k}`);
};

export const obj = (fields: Record<string, Check>): Check => (v, p) => {
  if (!isPlainObject(v)) fail(p, "объект");
  const o = v as Record<string, unknown>;
  for (const [k, check] of Object.entries(fields)) check(o[k], `${p}.${k}`);
};

export const anyObj: Check = obj({});

const nullNum = nullable(num);
const nullStr = nullable(str);
const strs = arr(str);
const nums = dict(num);

const planStep = obj({
  time_hours: num, controls: nums, recipe: nums, throughput_tph: nullNum, additive_dose: nullNum
});

const gateCheck = obj({
  constraint_id: str, status: oneOf("pass", "fail", "unknown"), observed: nullNum, limit: nullNum,
  time_hours: nullNum, reason: str
});

const gate = obj({
  plan_id: nullStr, feasible: bool, checks: arr(gateCheck), first_violation: nullable(gateCheck),
  unknown_requirements: strs, rejection_reasons: strs
});

const candidate = obj({
  candidate_id: str, production_t: optNull(num), cost_per_tonne: optNull(num), severity_index: optNull(num),
  changes: optNull(num), feasible: opt(bool), rejection_reasons: opt(strs)
});

const robustness = obj({
  plan_id: nullStr, perturbations_declared: num, perturbations_evaluated: num, held: num, violated: num,
  not_applicable: num, share_holding: nullNum, fragile: bool,
  results: arr(obj({ perturbation: str, outcome: str })), mandatory_failure_names: opt(strs), limits: opt(strs)
});

const lookaheadLeg = obj({
  plan_id: nullStr, hours_to_violation: optNull(num), constraint: optNull(str), observed: optNull(num),
  limit: optNull(num)
});

const lookahead = obj({
  available: bool, lookahead_hours: nullNum, min_reaction_hours: optNull(num), initial_plan: optNull(str),
  initial: optNull(lookaheadLeg), selected: optNull(lookaheadLeg), switched: bool, examined: opt(num),
  warning: nullStr, offspec: optNull(anyObj)
});

const deploymentReadiness = obj({
  ready: bool, reason: str,
  required_inputs: arr(obj({
    id: str, label: str, status: oneOf("open", "given"), unit: str, required_values: strs,
    scenario_assumptions: dict(nullNum), impact: str
  }))
});

const severityMode = obj({
  available: bool, index: optNull(num), profile_id: opt(str), profile_version: opt(str),
  components: opt(arr(obj({ term: str, contribution: num }))),
  limits: opt(arr(obj({ kind: oneOf("passport", "model_region", "scenario"), label: str, known: bool, note: str })))
});

const severity = obj({
  current: nullable(severityMode), selected: nullable(severityMode), comparable: bool, delta: nullNum, rule: str
});

const tradeoffPoint = obj({
  candidate_id: str, production_t: num, cost_per_tonne: num, severity_index: num, changes: num, on_front: bool,
  dominated_by: nullStr, selected: bool, is_hold: bool, recipe: nums, throughput_tph: nullNum,
  additive_dose: nullNum, moves: arr(obj({ name: str, from: num, to: num })), gate_passed: bool,
  stress_checked: bool, equivalent_count: num, equivalent_ids: strs
});

const tradeoff = obj({
  version: str, status: oneOf("ok", "empty", "unknown_metrics"),
  criteria: arr(obj({ key: str, label: str, unit: str, goal: oneOf("min", "max") })), precision: num,
  horizon_hours: nullNum, severity_profile: nullStr,
  pool: obj({ admissible: num, front: num, excluded_unknown_count: num, points_shown: num, points_truncated: bool }),
  selected_id: nullStr, selected_on_front: nullable(bool), selection_note: nullStr, selection_reason: nullStr,
  hold: obj({ id: str, admissible: bool }), points: arr(tradeoffPoint), scope: str, stress_scope: str
});

const consequencePoint = obj({ t: num, value: nullNum, status: oneOf("pass", "fail", "unknown") });

const consequenceCandidate = obj({ candidate_id: str, points: arr(consequencePoint) });

const consequenceSeries = obj({
  limit_id: str, quality: str, unit: nullStr, direction: oneOf("max", "min", "unknown"),
  limit: obj({ value: nullNum, source: nullStr }),
  candidates: obj({ selected: consequenceCandidate, hold: opt(consequenceCandidate) })
});

const consequenceEvent = obj({
  kind: oneOf("control", "blend"), origin: oneOf("plan", "confirmed"), t: num, response_t: num, lag_hours: num,
  lag_source: str, stage: opt(str), controls: opt(nums), changed: opt(strs), recipe: opt(nums),
  throughput_tph: opt(num), additive_dose: opt(num), partial_response: opt(obj({ share: num, until_hours: num }))
});

const consequences = obj({
  version: num, selected_id: str, horizon_hours: num, step_hours: num, series: arr(consequenceSeries),
  applicability: obj({
    selected: arr(obj({ t: num, value: str })), hold: opt(arr(obj({ t: num, value: str })))
  }),
  hold: obj({ available: bool, candidate_id: nullStr, source: nullStr, reason: nullStr }), note: str,
  events: opt(obj({ selected: nullable(arr(consequenceEvent)), hold: optNull(arr(consequenceEvent)) })),
  events_note: opt(str)
});

const choiceEvidence = obj({
  decision_id: nullStr, candidate_id: str, constraint_id: nullStr, status: oneOf("pass", "fail", "unknown"),
  time_hours: nullNum, observed: nullNum, limit: nullNum, unit: nullStr, limit_source: nullStr, reason: str,
  points: num
});

const choiceReason = obj({
  category: str, stage: str, text: str, evidence: opt(arr(choiceEvidence)), evidence_total: opt(num),
  rule: opt(obj({ id: str, value: nullNum, observed: nullable(either(num, bool)), source: str })),
  events: opt(strs)
});

const choiceCard = obj({
  candidate_id: str, production_t: nullNum, cost_per_tonne: nullNum, severity_index: nullNum, changes: nullNum,
  verdict: oneOf("selected", "admissible_not_selected", "excluded"), reasons: arr(choiceReason)
});

const choice = obj({
  version: num, decision_id: nullStr, status: str, selected_id: nullStr, hold_id: nullStr, hold_examined: bool,
  cheaper_id: nullStr, cheaper_count: num, cheaper_note: nullStr,
  determined_by: arr(obj({ stage: str, text: nullStr, candidate_ids: arr(nullStr) })),
  pool: obj({ examined: num, admissible_final: num, scope: str, allowed_by_agents: opt(num) }),
  candidates: arr(choiceCard), rule: str,
  refusal: nullable(obj({ kind: nullStr, stage: str, agents_skipped: bool, domain_impossibility_proven: bool })),
  agents: opt(obj({
    vetoed: strs, constraints: arr(anyObj), allowed: num, legacy_plan_id: nullStr, legacy_excluded: bool,
    selected_changed: bool, note: str
  }))
});

const opinion = obj({
  role: str, verdict: str, risk_level: nullStr, confidence: nullNum, valid: bool,
  reasons: arr(obj({ code: str, text: str })), proposed_constraints: opt(arr(obj({ type: str })))
});

const agentic = obj({
  mode: str, outcome: str, fallback_reason: nullStr, legacy_decision_id: nullStr, legacy_status: nullStr,
  provider: nullStr, model: nullStr, note: str, deterministic_policy: opt(bool), opinions: opt(arr(opinion)),
  vetoed_candidates: opt(dict(strs)), constraints_applied: opt(arr(obj({ type: str }))),
  final: optNull(obj({ action: str, candidate_id: nullStr, reason_codes: strs, summary: str })),
  budget: opt(anyObj), trace: opt(arr(any))
});

const decision = obj({
  status: oneOf("hold", "recommend_scenario", "refuse"), reason: str, scope: nullStr,
  current_operation: optNull(anyObj), commercial_release_allowed: bool, deployment_readiness: opt(deploymentReadiness),
  scenario_id: nullStr,
  selected_plan: nullable(obj({ plan_id: str, intent: str, changes: num, steps: arr(planStep) })),
  immediate_action: nullable(planStep), gate: nullable(gate), production_t: nullNum, cost_per_tonne: nullNum,
  severity_index: nullNum, alternatives: arr(candidate), rejected: arr(any),
  refusal: nullable(obj({ kind: str, examples: opt(strs), missing: opt(strs) })), robustness: nullable(robustness),
  lookahead: nullable(lookahead), selection_policy: nullable(anyObj), trace: arr(obj({})), note: nullStr,
  decision_id: nullStr, agentic: optNull(agentic), severity: optNull(severity), tradeoff: optNull(tradeoff),
  consequences: optNull(consequences), choice: optNull(choice)
});

const currentOperation = obj({
  controls: dict(nullNum), recipe: dict(nullNum), throughput_tph: nullNum, additive_dose: nullNum, origin: nullable(anyObj)
});

const explanation = obj({
  status: str, reason: str, kind: opt(str),
  statements: opt(arr(obj({
    topic: str, text: str, value: nullNum,
    evidence: arr(obj({ kind: str, ref: str, value: nullNum, detail: str }))
  }))),
  next_steps: opt(arr(obj({ need: str, kind: str }))), current_operation: nullable(currentOperation),
  component_names: dict(str), warnings: opt(arr(obj({ kind: str, text: str, observed_margin_mgkg: opt(num) }))),
  risk: nullable(obj({ level: str, items: arr(obj({ kind: str, level: str, text: str })), headline: str, scope: str })),
  checks_passed: opt(num), checks_total: opt(num),
  alternatives: opt(arr(obj({ candidate_id: str, why_not: str }))), comparison_rule: opt(str), limits: strs,
  plan_origin: optNull(obj({ immediate_action: nullable(anyObj), steps: arr(anyObj), rule: str })),
  chain: optNull(obj({ mode: oneOf("live", "scenario"), blocks: arr(obj({ id: str, label: str, controllable: bool })) }))
});

const source = obj({
  name: str, status: str, value: nullNum, age_hours: nullNum, max_age_hours: nullNum, reasons: strs, usable: bool
});

const appliedChange = obj({ change: str, value: either(num, bool), target: opt(str) });

export const runMetaShape = obj({
  schema: str, created_at: nullStr, conditions_requested: nullable(dict(either(str, num, bool, (v, p) => {
    if (v !== null) fail(p, "null");
  }))),
  conditions_applied: nullable(obj({
    changes: arr(appliedChange), snapshot: nullStr, fault: nullStr, injection: nullStr, decision_time: nullStr
  })),
  input_fingerprint: nullStr, input_parts: nullable(anyObj),
  code: nullable(obj({ commit: nullStr, dirty: nullable(bool), note: nullStr })),
  model: nullable(obj({ response_model_sha256: nullStr, training_fingerprint: nullStr })),
  provider: nullable(obj({
    provider: nullStr, model: nullStr, deterministic_policy: nullable(bool), mode: nullStr, outcome: nullStr
  })),
  horizon_hours: nullNum, severity_profile: nullStr
});

export const payloadShape = obj({
  state: oneOf("decision", "refusal"), title: str, status_label: str, decision, explanation,
  inventories: nums, sources: arr(source), rule_origin: nullStr, state_origin: nullStr, decision_time: nullStr,
  forecast: nullable(anyObj), forecast_used: optNull(bool),
  defaults: opt(obj({
    tanks: opt(arr(obj({ id: str, inventory: nullNum, on_demand: bool, available: bool })))
  })),
  applied: opt(arr(appliedChange)), injection: optNull(str), snapshot: optNull(str), binding: optNull(anyObj),
  run_meta: optNull(runMetaShape), decision_timeout_s: opt(num),
  agentic_state: opt(obj({ mode: str, outcome: str, reason: str, note: str }))
});

export const FORM_FIELDS = [
  "scenario", "snapshot", "fault", "crude_sulfur_wt_pct", "product_sulfur_mgkg", "product_t95_c",
  "product_cetane_number", "throughput_tph", "tank", "tank_inventory", "tank_available"
] as const;

export const formShape = obj(Object.fromEntries(FORM_FIELDS.map((key) => [key, opt(str)])));
