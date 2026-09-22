import type { Agentic, ProposedConstraint, RunMeta, ScreenPayload } from "../../types";
import type { RunState } from "../../run/types";
import { contributionModel } from "../../agents/contribution";
import type { AgentCardModel } from "../../agents/contribution";
import { OUTCOME_TEXT, constraintDetail, skippedText } from "../../agents/vocab";
import { CONSTRAINT_TEXT } from "../../run/agentVocab";
import { isNumber, moment, num, percent } from "../../format";
import { originMeta } from "../../provenance";
import type { ResearchSummary } from "./research";
import { modelLink } from "./research";

export const UNKNOWN = "неизвестно";

export type RowTone = "ok" | "warn" | "unknown" | "plain";

/** Одна строка паспорта: значение и точное место, откуда оно взято. */
export interface PassportRow {
  key: string;
  label: string;
  value: string;
  source: string;
  tone: RowTone;
}

export interface PassportSection {
  rows: PassportRow[];
  notes: string[];
}

/** Ссылка на уже доказанную связь «ограничение → исключённый кандидат / изменённый итог». */
export interface InfluenceRef {
  text: string;
  href?: string;
}

/** Ключ ограничения для influenceRefs: `type|limit|value`, как в constraints_applied. */
export function constraintKey(item: ProposedConstraint): string {
  return [item.type, item.limit ?? "", typeof item.value === "number" ? String(item.value) : ""].join("|");
}

export interface AgentConstraintRow {
  key: string;
  role: string;
  label: string;
  detail: string | null;
  applied: boolean;
  influence: InfluenceRef;
}

export interface AgentRoleRow {
  key: string;
  title: string;
  state: string;
  validity: string;
  effect: string;
  invalid: boolean;
}

export interface AgentsSection extends PassportSection {
  mode: AgentMode;
  roles: AgentRoleRow[];
  constraints: AgentConstraintRow[];
}

export type AgentMode = "live" | "scripted" | "fallback" | "skipped" | "disabled" | "absent";

export interface PassportMark {
  /** Маркировка на печатном листе: чей это расчёт и откуда он в окне. */
  origin: "record" | "live" | "result";
  text: string;
  scenario: string;
  decision: string;
}

export interface PassportModel {
  mark: PassportMark;
  input: PassportSection;
  verified: PassportSection & { available: boolean; link: ReturnType<typeof modelLink> | null };
  agents: AgentsSection;
}

export interface PassportInput {
  run: RunState;
  research?: ResearchSummary | null;
  influenceRefs?: Record<string, InfluenceRef>;
}

const NOT_ESTABLISHED: InfluenceRef = {
  text: "влияние на выбор не установлено: повторного расчёта без этого ограничения на тех же условиях нет"
};

function short(hash: string | null | undefined): string | null {
  return typeof hash === "string" && hash.length > 0 ? hash.slice(0, 12) : null;
}

function row(key: string, label: string, value: string | null, source: string, tone: RowTone = "plain"): PassportRow {
  return value === null
    ? { key, label, value: UNKNOWN, source, tone: "unknown" }
    : { key, label, value, source, tone };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function markOf(run: RunState, payload: ScreenPayload): PassportMark {
  const scenario = payload.state_origin ?? (payload.snapshot ? `срез ${payload.snapshot}` : "происхождение состояния не передано");
  const decision = `${payload.title} · ${payload.status_label}`;
  if (run.record) {
    return {
      origin: "record", scenario, decision,
      text: `Запись «${run.record.label}» от ${moment(run.record.recordedAt)} (${run.record.runId}). Паспорт относится к этой записи, а не к текущим настройкам сервера.`
    };
  }
  if (run.live) {
    return { origin: "live", scenario, decision, text: "Расчёт выполнен в этом окне; при экспорте паспорт уйдёт вместе с записью." };
  }
  return { origin: "result", scenario, decision, text: "Результат без записи: сведения только из ответа сервера." };
}

function controlRows(payload: ScreenPayload): PassportRow[] {
  const controls = record(record(payload.binding)?.controls);
  if (!controls) return [];
  return Object.entries(controls).map(([name, raw]) => {
    const current = record(record(raw)?.current);
    const value = current?.value;
    const source = typeof current?.source === "string" ? current.source : null;
    const meta = originMeta(source);
    const text = isNumber(value) ? `${num(value, 2)} · ${meta ? meta.short : source ?? UNKNOWN}` : null;
    return row(`control-${name}`, name, text, `payload.binding.controls.${name}.current`,
      source === "measured" ? "ok" : source === null ? "unknown" : "plain");
  });
}

function inputSection(run: RunState, payload: ScreenPayload): PassportSection {
  const meta: RunMeta | null = payload.run_meta ?? null;
  const notes: string[] = [];
  const rows: PassportRow[] = [];

  rows.push(row("decision-time", "Момент решения",
    payload.decision_time ?? meta?.conditions_applied?.decision_time ?? null, "payload.decision_time"));
  rows.push(row("state-origin", "Состояние установки", payload.state_origin ?? null, "payload.state_origin",
    payload.snapshot ? "ok" : "warn"));
  if (payload.injection) {
    rows.push(row("injection", "Наложенный отказ", payload.injection, "payload.injection", "warn"));
  }

  for (const source of payload.sources ?? []) {
    const age = isNumber(source.age_hours) ? `${num(source.age_hours, 2)} ч` : null;
    const limit = isNumber(source.max_age_hours) ? ` из допустимых ${num(source.max_age_hours, 2)} ч` : "";
    const verdict = source.usable ? "пригоден" : `не пригоден${source.reasons[0] ? `: ${source.reasons[0]}` : ""}`;
    rows.push(row(`source-${source.name}`, `Возраст: ${source.name}`, age === null ? null : `${age}${limit}, ${verdict}`,
      `payload.sources[${source.name}]`, source.usable ? "ok" : "warn"));
  }
  rows.push(...controlRows(payload));

  const applied = payload.applied ?? meta?.conditions_applied?.changes ?? [];
  rows.push(row("applied", "Изменённые условия",
    applied.length === 0 ? "нет: условия сценария без правок"
      : applied.map((item) => `${item.change}${item.target ? `(${item.target})` : ""} = ${String(item.value)}`).join("; "),
    "payload.applied", applied.length === 0 ? "plain" : "warn"));

  const response = record(record(payload.binding)?.response_model);
  const beta = response?.beta_mgkg_per_c;
  rows.push(row("response", "Модель отклика серы на T6",
    isNumber(beta) ? `β = ${num(beta, 4)} мг/кг/°C · ${originMeta(String(response?.provenance))?.short ?? String(response?.provenance ?? UNKNOWN)}` : null,
    "payload.binding.response_model"));

  if (meta === null) {
    notes.push("В записи нет run_meta: версия кода и модели неизвестны. Текущие настройки сервера вместо них не подставляются.");
  }
  rows.push(row("model", "Модель (отпечаток обучения)", short(meta?.model?.training_fingerprint), "run_meta.model.training_fingerprint"));
  rows.push(row("model-file", "Файл модели отклика (SHA-256)", short(meta?.model?.response_model_sha256), "run_meta.model.response_model_sha256"));
  const code = meta?.code;
  rows.push(row("code", "Код", code?.commit
    ? `${short(code.commit)}${code.dirty === true ? ", есть незакоммиченные правки" : code.dirty === false ? ", дерево чистое" : ", состояние дерева неизвестно"}`
    : null, "run_meta.code", code?.dirty === true ? "warn" : "plain"));
  rows.push(row("fingerprint", "Отпечаток входов", short(meta?.input_fingerprint), "run_meta.input_fingerprint"));
  rows.push(row("horizon", "Горизонт решения", isNumber(meta?.horizon_hours) ? `${num(meta?.horizon_hours, 1)} ч` : null, "run_meta.horizon_hours"));

  const decision = payload.decision;
  rows.push(row("scope", "Область применимости", decision.scope ?? null, "payload.decision.scope"));
  const ready = decision.deployment_readiness;
  rows.push(row("readiness", "Готовность к промышленному применению",
    ready ? `${ready.ready ? "да" : "нет"}${ready.reason ? ` — ${ready.reason}` : ""}` : null,
    "payload.decision.deployment_readiness", ready?.ready ? "ok" : "warn"));
  rows.push(row("release", "Коммерческий выпуск разрешён", decision.commercial_release_allowed ? "да" : "нет",
    "payload.decision.commercial_release_allowed", decision.commercial_release_allowed ? "ok" : "warn"));

  if (!run.record && !run.live) notes.push("Происхождение окна не отмечено: это не живой расчёт и не открытая запись.");
  return { rows, notes };
}

const OBJECT_TEXT: Record<string, string> = {
  stream_after_hydrotreating: "поток ДТ после гидроочистки"
};
const TARGET_TEXT: Record<string, string> = {
  next_lims_sample: "следующая лабораторная проба ЛИМС"
};

function verifiedSection(payload: ScreenPayload, research: ResearchSummary | null): PassportModel["verified"] {
  if (research === null) {
    return {
      available: false, link: null, rows: [],
      notes: ["Исследовательская сводка к этому паспорту не передана: подтверждённое качество прогноза здесь не показывается."]
    };
  }
  const file = research.sources[0]?.path ?? research.document;
  const { baseline, winner, goal } = research;
  const unit = research.subject.unit;
  const diff = research.paired_mae_difference;
  const link = modelLink(research, payload.run_meta);
  const rows: PassportRow[] = [
    row("subject", "Что прогнозируется",
      `${research.subject.quantity === "sulfur_mgkg" ? "сера" : research.subject.quantity}, ${OBJECT_TEXT[research.subject.object] ?? research.subject.object}; цель — ${TARGET_TEXT[research.subject.target] ?? research.subject.target}`,
      research.subject.reference),
    row("period", "Период проверки", `${research.period}, единственный прогон после заморозки выбора`, `${file} · period`),
    row("sample", "Размер выборки", `${research.paired_targets} парных проб из ${research.total_targets}`, `${file} · paired_available_targets`),
    row("baseline", "Базовая линия", `${baseline.method}: MAE ${num(baseline.mae_mgkg, 3)} ${unit}`, `${file} · baseline.mae_mgkg`),
    row("winner", "Метод", `${winner.method}: MAE ${num(winner.mae_mgkg, 3)} ${unit}`, `${file} · winner.mae_mgkg`, "ok"),
    row("diff", "Разность MAE (метод − база)",
      `${num(diff.value_mgkg, 3)} ${unit}, 95% CI [${num(diff.ci95_mgkg[0], 3)}; ${num(diff.ci95_mgkg[1], 3)}], bootstrap ${diff.bootstrap_draws}`,
      `${file} · paired_mae_winner_minus_baseline`, diff.ci95_mgkg[1] < 0 ? "ok" : "warn"),
    row("upper", "Средний верхний запас", `${num(baseline.mean_upper_margin_mgkg, 3)} → ${num(winner.mean_upper_margin_mgkg, 3)} ${unit}`,
      `${file} · mean_upper_margin_mgkg`),
    row("exceed", "Доля фактов выше верхней границы",
      `${percent(winner.exceed_upper, 2)} у метода, ${percent(baseline.exceed_upper, 2)} у базы; цель ≤ ${percent(goal.max, 0)} ${goal.met_by_winner ? "достигнута" : "не достигнута"}`,
      `${file} · winner.exceed_upper; ${goal.reference}`, goal.met_by_winner ? "ok" : "warn"),
    row("selection", "Выбор метода",
      research.selection.frozen_before_period
        ? `заморожен до периода проверки${research.selection.changed_by_result ? ", но результат изменил выбор" : "; результат выбор не менял"}`
        : "не был заморожен до проверки",
      `${file} · run_policy`, research.selection.frozen_before_period && !research.selection.changed_by_result ? "ok" : "warn")
  ];
  const notes = [
    "Это прогноз серы потока до лабораторной пробы. Он не описывает качество товарной смеси, оценку содержимого резервуара и модель последствий плана; у оценки резервуара независимой проверки нет.",
    `Цель ≤ ${percent(goal.max, 0)} — собственная исследовательская цель протокола, не требование ТЗ. Граница — эмпирический диапазон, не гарантия.`
  ];
  if (link === "evaluated") {
    notes.unshift("Проверка выполнена на модели с тем же отпечатком обучения, что у этой записи.");
  } else if (link === "declared") {
    notes.unshift("Отпечаток модели записи совпадает с заявленным после усиления метаданных; сам прогон 2026 на нём не повторялся. Исследовательский результат, не прямое доказательство этой модели.");
  } else if (link === "other") {
    notes.unshift("Модель этой записи отличается от проверенной (другой отпечаток обучения). Это исследовательский результат, не доказательство качества текущей модели.");
  } else {
    notes.unshift("Версия модели записи неизвестна: связь исследования с ней не установлена. Это исследовательский результат, не доказательство текущей модели.");
  }
  if (payload.forecast_used === false) notes.push("В этом расчёте прогноз не использовался.");
  return { available: true, link, rows, notes };
}

function modeOf(payload: ScreenPayload, agentic: Agentic | null): AgentMode {
  if (agentic === null) return payload.agentic_state?.mode === "disabled" ? "disabled" : "absent";
  if (agentic.outcome === "skipped") return "skipped";
  if (agentic.outcome === "fallback") return "fallback";
  if (agentic.deterministic_policy === true || agentic.provider === "scripted") return "scripted";
  return "live";
}

function modeText(mode: AgentMode, payload: ScreenPayload, agentic: Agentic | null): string {
  const who = agentic ? [agentic.provider, agentic.model].filter(Boolean).join(" / ") || UNKNOWN : UNKNOWN;
  switch (mode) {
    case "live": return `Живая LLM (${who}).`;
    case "scripted": return `Scripted-политика (${who}): детерминированные ответы без обращения к внешней LLM.`;
    case "fallback": return `Сбой агентного этапа, запасной путь (${who}). Причина: ${agentic?.fallback_reason ?? "не передана"}.`;
    case "skipped": return skippedText(payload, agentic as Agentic) ?? "Агенты не запускались.";
    case "disabled": return `Агентный слой выключен (${payload.agentic_state?.reason ?? "причина не передана"}).`;
    case "absent": return "Агентного слоя в этом результате нет.";
  }
}

function validity(card: AgentCardModel, agentic: Agentic): string {
  if (card.key === "orchestrator") return agentic.final ? "итог передан" : "итога нет";
  const opinion = (agentic.opinions ?? []).find((item) => item.role === card.key);
  if (!opinion) return "мнение не подано";
  return opinion.valid ? "мнение валидно" : "мнение отклонено как невалидное";
}

function agentsSection(run: RunState, payload: ScreenPayload, influenceRefs: Record<string, InfluenceRef>): AgentsSection {
  const agentic = payload.decision.agentic ?? null;
  const mode = modeOf(payload, agentic);
  const rows: PassportRow[] = [row("mode", "Режим", modeText(mode, payload, agentic), "decision.agentic.mode/provider",
    mode === "live" || mode === "scripted" ? "plain" : "warn")];
  const notes: string[] = [];
  if (agentic === null || mode === "skipped") return { mode, rows, notes, roles: [], constraints: [] };

  const contribution = contributionModel(run);
  const roles = contribution.cards.map((card) => ({
    key: card.key, title: card.title, state: card.state, validity: validity(card, agentic),
    effect: card.effect, invalid: card.invalid
  }));

  const applied = agentic.constraints_applied ?? [];
  const constraints: AgentConstraintRow[] = [];
  for (const opinion of agentic.opinions ?? []) {
    for (const [index, item] of (opinion.proposed_constraints ?? []).entries()) {
      const key = constraintKey(item);
      const isApplied = opinion.valid && applied.some((other) => constraintKey(other) === key);
      constraints.push({
        key: `${opinion.role}-${index}`, role: opinion.role, label: CONSTRAINT_TEXT[item.type] ?? item.type,
        detail: constraintDetail(item), applied: isApplied,
        influence: isApplied ? influenceRefs[key] ?? NOT_ESTABLISHED
          : { text: opinion.valid ? "не применено" : "не применено: мнение невалидно" }
      });
    }
  }
  for (const [index, item] of applied.entries()) {
    const key = constraintKey(item);
    if ((agentic.opinions ?? []).some((opinion) => (opinion.proposed_constraints ?? []).some((p) => constraintKey(p) === key))) continue;
    constraints.push({
      key: `applied-${index}`, role: "orchestrator", label: CONSTRAINT_TEXT[item.type] ?? item.type,
      detail: constraintDetail(item), applied: true, influence: influenceRefs[key] ?? NOT_ESTABLISHED
    });
  }

  const final = agentic.final ?? null;
  const unchanged = agentic.outcome === "confirmed_legacy" || final?.action === "keep_legacy";
  rows.push(row("outcome", "Окончательный исход",
    `${OUTCOME_TEXT[agentic.outcome] ?? agentic.outcome}${final?.candidate_id ? ` (${final.candidate_id})` : ""}${unchanged ? "; выбор не изменился" : ""}`,
    "decision.agentic.outcome/final", agentic.outcome === "fallback" ? "warn" : "plain"));
  if (!unchanged && agentic.outcome === "selected") {
    notes.push("Выбор после проверки агентов зафиксирован, но сравнения с выбором без них на тех же условиях в записи нет: улучшение не утверждается.");
  }

  const budget = agentic.budget;
  const byRole = budget?.llm_calls_by_role ?? {};
  rows.push(row("calls", "Вызовы модели",
    isNumber(budget?.llm_calls)
      ? `${budget.llm_calls}${isNumber(budget.max_llm_calls) ? ` из ${budget.max_llm_calls}` : ""}${Object.keys(byRole).length > 0 ? ` (${Object.entries(byRole).map(([role, calls]) => `${role} ${calls}`).join(", ")})` : ""}`
      : null,
    "decision.agentic.budget.llm_calls"));

  const trace = Array.isArray(agentic.trace) ? agentic.trace : [];
  const latencies = trace
    .map((item) => record(item))
    .filter((item): item is Record<string, unknown> => item !== null && item["kind"] === "llm_call")
    .map((item) => item["latency_ms"]);
  const known = latencies.filter(isNumber);
  const time = latencies.length === 0 || known.length < latencies.length
    ? null
    : `${num(known.reduce((sum, value) => sum + value, 0) / 1000, 1)} с суммарно по ${known.length} вызовам${mode === "scripted" ? " (scripted: без сетевого вызова)" : ""}`;
  rows.push(row("time", "Время ответов модели", time, "decision.agentic.trace[kind=llm_call].latency_ms"));
  if (isNumber(run.serverMs)) {
    rows.push(row("run-time", "Время всего расчёта", `${num(run.serverMs / 1000, 1)} с`, "запись: кадр screen"));
  }

  const usage = budget?.usage;
  const total = usage?.["total_tokens"];
  rows.push(row("tokens", "Токены",
    isNumber(total)
      ? `${total.toLocaleString("ru-RU")}${isNumber(usage?.["prompt_tokens"]) && isNumber(usage?.["completion_tokens"]) ? ` (вход ${usage["prompt_tokens"]!.toLocaleString("ru-RU")}, выход ${usage["completion_tokens"]!.toLocaleString("ru-RU")})` : ""}${mode === "scripted" ? "; scripted не расходует токены" : ""}`
      : null,
    "decision.agentic.budget.usage"));
  const cost = usage?.["cost_usd"];
  rows.push(row("cost", "Стоимость", isNumber(cost) ? `${num(cost, 4)} USD` : null, "decision.agentic.budget.usage.cost_usd"));
  if (!isNumber(cost)) notes.push("Стоимость неизвестна: ни провайдер, ни запись цену вызовов не передают. Это не ноль.");

  return { mode, rows, notes, roles, constraints };
}

export function passportModel({ run, research = null, influenceRefs = {} }: PassportInput): PassportModel | null {
  const payload = run.payload;
  // Паспорт — о завершённом расчёте: промежуточное состояние прогона сюда не попадает.
  if (payload === null || run.status === "running") return null;
  return {
    mark: markOf(run, payload),
    input: inputSection(run, payload),
    verified: verifiedSection(payload, research),
    agents: agentsSection(run, payload, influenceRefs)
  };
}
