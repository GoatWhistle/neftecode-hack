import type { AgentEvent } from "./types";
import { TRUNCATION_MARK, boolAt, constraintText, decimal, limitText, numberAt, objectsAt,
  parseObject, plural, rankKeyText, salvage, stringAt, stringsAt } from "./orchRead";
import { VERDICT_TEXT } from "../agents/vocab";

export interface OrchFact {
  label: string;
  value: string;
}

export interface OrchRank {
  keys: string[];
  reason: string | null;
}

export interface OrchReading {
  tool: string;
  title: string;
  asked: string | null;
  askedIds: string[];
  question: string | null;
  facts: OrchFact[];
  rank: OrchRank | null;
  inputTruncated: boolean;
  resultTruncated: boolean;
  inputRaw: string | null;
  resultRaw: string | null;
  resultFull: string | null;
  resultParsed: boolean;
  resultPartial: boolean;
  failed: boolean;
  error: string | null;
}

const TITLE: Record<string, string> = {
  inspect_candidate: "посмотрел план",
  compare_candidates: "сравнил планы",
  search_candidates: "запустил поиск с ограничениями",
  rank_allowed: "запросил ранжирование допущенных",
  ask_quality_agent: "спросил агента качества",
  ask_reliability_agent: "спросил агента надёжности"
};

export const SPECIALIST_TOOL_TEXT: Record<string, string> = {
  get_quality_margins: "запас качества",
  get_forecast_and_uncertainty: "прогноз и разброс",
  get_tank_projection: "проекция резервуара",
  get_setpoint_changes: "перестановки уставок",
  get_robustness: "устойчивость к возмущениям"
};

function cut(text: string): boolean {
  return text.endsWith(TRUNCATION_MARK);
}

function marginFacts(source: Record<string, unknown> | null): OrchFact[] {
  const margins = source?.["min_margins"];
  if (margins === null || typeof margins !== "object" || Array.isArray(margins)) return [];
  const out: OrchFact[] = [];
  for (const [key, raw] of Object.entries(margins as Record<string, unknown>)) {
    if (typeof raw !== "number" || !Number.isFinite(raw)) continue;
    out.push({ label: `запас · ${limitText(key)}`, value: decimal(raw, 3) });
  }
  return out.slice(0, 4);
}

function inspectFacts(result: Record<string, unknown> | null): OrchFact[] {
  const card = result?.["card"];
  const source = card !== null && typeof card === "object" && !Array.isArray(card)
    ? (card as Record<string, unknown>)
    : result;
  const out: OrchFact[] = [];
  const changes = numberAt(source, "changes");
  if (changes !== null) {
    out.push({ label: "переключений",
      value: `${changes} ${plural(changes, "изменение", "изменения", "изменений")}` });
  }
  const gate = boolAt(source, "gate_feasible");
  if (gate !== null) out.push({ label: "Gate", value: gate ? "пройден" : "не пройден" });
  const production = numberAt(source, "production_t");
  if (production !== null) out.push({ label: "выпуск", value: `${decimal(production, 1)} т` });
  const cost = numberAt(source, "cost_per_tonne");
  if (cost !== null) out.push({ label: "затраты", value: `${decimal(cost, 3)} у.е./т` });
  return [...out, ...marginFacts(source)];
}

function compareFacts(result: Record<string, unknown> | null): OrchFact[] {
  const rows = objectsAt(result, "candidates");
  if (rows === null) return [];
  const named = rows.map((row) => stringAt(row, "id")).filter((id): id is string => id !== null);
  const out: OrchFact[] = [{ label: "планов в сравнении", value: String(rows.length) }];
  if (named.length > 0) out.push({ label: "какие", value: named.join(", ") });
  const failed = rows.filter((row) => stringAt(row, "error") !== null).length;
  if (failed > 0) out.push({ label: "не удалось прочитать", value: String(failed) });
  return out;
}

function searchFacts(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const added = objectsAt(result, "constraints_added");
  if (added !== null) {
    out.push({ label: "ограничений добавлено",
      value: added.length === 0 ? "ни одного" : added.map(constraintText).join("; ") });
  }
  const active = objectsAt(result, "constraints_active");
  if (active !== null) out.push({ label: "ограничений в силе", value: String(active.length) });
  const rejected = objectsAt(result, "constraints_rejected");
  if (rejected !== null && rejected.length > 0) {
    out.push({ label: "ограничений отклонено", value: String(rejected.length) });
  }
  const fresh = numberAt(result, "newly_evaluated");
  if (fresh !== null) out.push({ label: "новых планов просчитано", value: String(fresh) });
  const freshOk = numberAt(result, "newly_feasible");
  if (freshOk !== null) out.push({ label: "из них прошли Gate", value: String(freshOk) });
  const feasible = numberAt(result, "feasible_total");
  const allowed = numberAt(result, "allowed_total");
  if (feasible !== null) out.push({ label: "прошли Gate всего", value: String(feasible) });
  if (allowed !== null) out.push({ label: "допущено после ограничений", value: String(allowed) });
  const left = numberAt(result, "evaluation_budget_left");
  if (left !== null) out.push({ label: "остаток бюджета перебора", value: String(left) });
  const skipped = numberAt(result, "not_evaluable");
  if (skipped !== null && skipped > 0) out.push({ label: "не поддались расчёту", value: String(skipped) });
  return out;
}

function rankOf(result: Record<string, unknown> | null): OrchRank | null {
  const keys = stringsAt(result, "ranking");
  const reason = stringAt(result, "reason");
  if (keys === null && reason === null) return null;
  return { keys: (keys ?? []).map(rankKeyText), reason };
}

function rankFacts(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const selected = stringAt(result, "selected");
  out.push({ label: "лучший по правилу", value: selected ?? "план не назван" });
  const alternatives = stringsAt(result, "alternatives");
  if (alternatives !== null) {
    out.push({ label: "рядом",
      value: alternatives.length === 0 ? "альтернатив нет" : alternatives.join(", ") });
  }
  const allowed = numberAt(result, "allowed_total");
  if (allowed !== null) out.push({ label: "ранжировано планов", value: String(allowed) });
  return out;
}

function consultFacts(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const opinion = result?.["opinion"];
  const source = opinion !== null && typeof opinion === "object" && !Array.isArray(opinion)
    ? (opinion as Record<string, unknown>)
    : null;
  const verdict = stringAt(source, "verdict");
  if (verdict !== null) {
    const said = VERDICT_TEXT[verdict];
    out.push({ label: "вердикт специалиста",
      value: said === undefined ? verdict : `${verdict} — ${said}` });
  }
  const risk = stringAt(source, "risk_level");
  if (risk !== null) out.push({ label: "уровень риска", value: risk });
  const vetoed = stringsAt(result, "vetoed_now");
  if (vetoed !== null) {
    out.push({ label: "исключено вердиктом",
      value: vetoed.length === 0 ? "ни одного плана" : vetoed.join(", ") });
  }
  const allowed = numberAt(result, "allowed_total");
  if (allowed !== null) out.push({ label: "допущено после мнения", value: String(allowed) });
  return out;
}

function marginRows(result: Record<string, unknown> | null): OrchFact[] {
  const margins = result?.["margins"];
  if (margins === null || typeof margins !== "object" || Array.isArray(margins)) return [];
  const out: OrchFact[] = [];
  for (const [key, raw] of Object.entries(margins as Record<string, unknown>)) {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) continue;
    const row = raw as Record<string, unknown>;
    const margin = numberAt(row, "min_margin");
    const status = stringAt(row, "status");
    if (margin === null && status === null) continue;
    const parts: string[] = [];
    if (margin !== null) parts.push(decimal(margin, 3));
    if (status !== null) parts.push(status === "pass" ? "в допуске" : status);
    out.push({ label: limitText(key), value: parts.join(" · ") });
  }
  return out.slice(0, 6);
}

function trustRows(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const trust = result?.["data_trust"];
  const source = trust !== null && typeof trust === "object" && !Array.isArray(trust)
    ? (trust as Record<string, unknown>)
    : null;
  const primary = stringAt(source, "primary");
  if (primary !== null) out.push({ label: "основной источник", value: primary });
  const usable = boolAt(source, "usable");
  if (usable !== null) out.push({ label: "данные пригодны", value: usable ? "да" : "нет" });
  const forecast = result?.["forecast"];
  const fc = forecast !== null && typeof forecast === "object" && !Array.isArray(forecast)
    ? (forecast as Record<string, unknown>)
    : null;
  const tank = numberAt(fc, "tank_sulfur_mgkg");
  if (tank !== null) out.push({ label: "сера в резервуаре", value: `${decimal(tank, 2)} мг/кг` });
  const origin = stringAt(fc, "tank_sulfur_source");
  if (origin !== null) out.push({ label: "откуда значение", value: origin });
  return out;
}

function tankRows(result: Record<string, unknown> | null): OrchFact[] {
  const tanks = result?.["tanks"];
  if (tanks === null || typeof tanks !== "object" || Array.isArray(tanks)) return [];
  const out: OrchFact[] = [];
  for (const [name, raw] of Object.entries(tanks as Record<string, unknown>)) {
    if (!Array.isArray(raw) || raw.length === 0) continue;
    const points = raw.filter((item): item is Record<string, unknown> =>
      item !== null && typeof item === "object" && !Array.isArray(item));
    const head = points[0];
    const tail = points[points.length - 1];
    if (head === undefined || tail === undefined) continue;
    const first = numberAt(head, "t_stock");
    const last = numberAt(tail, "t_stock");
    const hours = numberAt(tail, "t");
    if (first === null || last === null) continue;
    const arrow = last > first ? "растёт" : last < first ? "убывает" : "без изменения";
    out.push({ label: `резервуар ${name}`,
      value: `${decimal(first, 0)} → ${decimal(last, 0)} т за ${hours === null ? "горизонт" : `${decimal(hours, 1)} ч`}, ${arrow}` });
  }
  return out.slice(0, 4);
}

function setpointRows(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const changes = numberAt(result, "changes");
  if (changes !== null) {
    out.push({ label: "переключений",
      value: `${changes} ${plural(changes, "изменение", "изменения", "изменений")}` });
  }
  const intent = stringAt(result, "intent");
  if (intent !== null) out.push({ label: "замысел плана", value: intent });
  const steps = objectsAt(result, "steps");
  if (steps !== null) out.push({ label: "шагов в плане", value: String(steps.length) });
  return out;
}

function robustnessRows(result: Record<string, unknown> | null): OrchFact[] {
  const out: OrchFact[] = [];
  const fragile = boolAt(result, "fragile");
  if (fragile !== null) {
    out.push({ label: "хрупкость", value: fragile ? "план хрупкий" : "план держится" });
  }
  const held = numberAt(result, "held");
  const evaluated = numberAt(result, "evaluated");
  if (held !== null && evaluated !== null) {
    out.push({ label: "выдержал возмущений", value: `${held} из ${evaluated}` });
  }
  const skipped = numberAt(result, "not_applicable");
  if (skipped !== null && skipped > 0) out.push({ label: "неприменимо", value: String(skipped) });
  const violated = objectsAt(result, "violated");
  if (violated !== null && violated.length > 0) {
    const names = violated
      .map((row) => stringAt(row, "perturbation"))
      .filter((name): name is string => name !== null);
    out.push({ label: "где сломался", value: names.length > 0 ? names.join("; ") : String(violated.length) });
  }
  return out;
}

export interface SpecialistReading {
  title: string;
  facts: OrchFact[];
  resultRaw: string | null;
  resultFull: string | null;
  failed: boolean;
}

export function readSpecialistTool(event: AgentEvent): SpecialistReading {
  const tool = event.tool_name ?? "инструмент без имени";
  const summaryRaw = event.tool_result_summary ?? null;
  const fullRaw = event.tool_result_full ?? null;
  const best = fullRaw !== null && fullRaw.length >= (summaryRaw?.length ?? 0) ? fullRaw : summaryRaw;
  const whole = parseObject(best ?? undefined);
  const result = whole ?? salvage(best ?? undefined);
  const failed = event.decision === "error";
  let facts: OrchFact[] = [];
  if (!failed) {
    if (tool === "get_quality_margins") facts = marginRows(result);
    else if (tool === "get_forecast_and_uncertainty") facts = trustRows(result);
    else if (tool === "get_tank_projection") facts = tankRows(result);
    else if (tool === "get_setpoint_changes") facts = setpointRows(result);
    else if (tool === "get_robustness") facts = robustnessRows(result);
  }
  return {
    title: SPECIALIST_TOOL_TEXT[tool] ?? tool,
    facts,
    resultRaw: summaryRaw,
    resultFull: fullRaw,
    failed
  };
}

export function readOrchTool(event: AgentEvent): OrchReading {
  const tool = event.tool_name ?? "инструмент без имени";
  const inputRaw = event.tool_input_summary ?? null;
  const summaryRaw = event.tool_result_summary ?? null;
  const fullRaw = event.tool_result_full ?? null;
  const resultRaw = fullRaw !== null && fullRaw.length >= (summaryRaw?.length ?? 0) ? fullRaw : summaryRaw;
  const input = parseObject(inputRaw ?? undefined);
  const whole = parseObject(resultRaw ?? undefined);
  const rescued = whole === null ? salvage(resultRaw ?? undefined) : null;
  const result = whole ?? rescued;
  const failed = event.decision === "error";
  const one = stringAt(input, "candidate_id");
  const askedIds = stringsAt(input, "candidate_ids") ?? (one !== null ? [one] : []);
  let facts: OrchFact[] = [];
  if (!failed) {
    if (tool === "inspect_candidate") facts = inspectFacts(result);
    else if (tool === "compare_candidates") facts = compareFacts(result);
    else if (tool === "search_candidates") facts = searchFacts(result);
    else if (tool === "rank_allowed") facts = rankFacts(result);
    else if (tool === "ask_quality_agent" || tool === "ask_reliability_agent") facts = consultFacts(result);
  }
  const constraintsAsked = objectsAt(input, "constraints");
  return {
    tool,
    title: TITLE[tool] ?? `вызвал инструмент ${tool}`,
    asked: askedIds.length > 0
      ? askedIds.join(", ")
      : constraintsAsked !== null && constraintsAsked.length > 0
        ? constraintsAsked.map(constraintText).join("; ")
        : null,
    askedIds: askedIds.length > 0 ? askedIds : (event.candidate_ids ?? []),
    question: stringAt(input, "focus"),
    facts,
    rank: tool === "rank_allowed" && !failed ? rankOf(result) : null,
    inputTruncated: inputRaw !== null && input === null && cut(inputRaw),
    resultTruncated: resultRaw !== null && whole === null && cut(resultRaw),
    inputRaw,
    resultRaw: summaryRaw,
    resultFull: fullRaw,
    resultParsed: whole !== null,
    resultPartial: whole === null && rescued !== null,
    failed,
    error: failed ? stringAt(result, "error") : null
  };
}
