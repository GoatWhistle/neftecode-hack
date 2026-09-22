import type { ScreenPayload } from "../types";
import { isNumber, num } from "../format";
import { changeLines, changeText } from "./changes";
import type { RunRecord } from "./record";
import { FAULT_LABELS } from "./options";
import { SCENARIO_LABEL } from "./orchRead";
import { canonicalJson } from "./canonical";

export interface DiffItem {
  key: string;
  label: string;
  a: string;
  b: string;
}

export interface PairRow {
  id: string;
  label: string;
  a: string;
  b: string;
  changed: boolean | null;
  delta: string | null;
  note: string | null;
}

export interface Incomparable {
  key: string;
  text: string;
}

export interface PairComparison {
  headline: string;
  answerChanged: boolean | null;
  inputDiff: DiffItem[];
  inputsKnown: boolean;
  identicalInputs: boolean | null;
  hiddenChanges: string[];
  unexplained: string | null;
  notApplied: string[];
  incomparable: Incomparable[];
  rows: PairRow[];
  notes: string[];
}

const CONDITION_LABELS: Record<string, string> = {
  scenario: "Сценарий",
  snapshot: "Момент решения",
  fault: "Внесённый отказ источника",
  crude_sulfur_wt_pct: "Сера сырья, % масс.",
  product_sulfur_mgkg: "Сера продукта, мг/кг",
  product_t95_c: "T95, °C",
  product_cetane_number: "Цетановое число",
  throughput_tph: "Производительность, т/ч",
  tank: "Резервуар",
  tank_inventory: "Запас в резервуаре, т",
  tank_available: "Доступность резервуара"
};

function conditionText(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "не задано";
  if (key === "scenario") return SCENARIO_LABEL[String(value)] ?? String(value);
  if (key === "fault") return FAULT_LABELS[String(value)] ?? String(value);
  if (key === "tank_available") return value === "1" || value === true ? "в работе" : "выведен";
  if (typeof value === "number") return num(value, 3);
  return String(value);
}

function equalCondition(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  return String(a ?? "") === String(b ?? "");
}

function requested(record: RunRecord): Record<string, unknown> | null {
  return record.meta?.conditions_requested ?? null;
}

export function inputDiff(a: RunRecord, b: RunRecord): DiffItem[] | null {
  const ra = requested(a);
  const rb = requested(b);
  if (!ra || !rb) return null;
  const keys = [...new Set([...Object.keys(ra), ...Object.keys(rb)])];
  const out: DiffItem[] = [];
  for (const key of keys) {
    if (equalCondition(ra[key], rb[key])) continue;
    out.push({ key, label: CONDITION_LABELS[key] ?? key, a: conditionText(key, ra[key]),
      b: conditionText(key, rb[key]) });
  }
  return out;
}

/** Изменённые пользователем поля, которые сервер не применил или заменил. */
export function notAppliedOf(record: RunRecord, against: RunRecord | null): string[] {
  const canonical = requested(record);
  const meta = record.meta;
  if (!canonical || !meta) return [];
  const out: string[] = [];
  const form = record.form as Record<string, string | undefined>;
  for (const [key, raw] of Object.entries(form)) {
    if (raw === undefined || raw === "" || !(key in canonical)) continue;
    const sent = Number(raw);
    const got = canonical[key];
    if (Number.isFinite(sent) && typeof got === "number" && !equalCondition(sent, got)) {
      out.push(`${CONDITION_LABELS[key] ?? key}: запрошено ${raw}, сервер применил ${num(got, 3)}`);
    } else if (!Number.isFinite(sent) && typeof got === "string" && raw !== got && key !== "tank") {
      out.push(`${CONDITION_LABELS[key] ?? key}: запрошено «${raw}», сервер применил «${got}»`);
    }
  }
  const defaults = record.payload.defaults as Record<string, unknown> | undefined;
  const applied = meta.conditions_applied?.changes ?? [];
  if (against && defaults) {
    const other = requested(against);
    for (const key of ["throughput_tph", "crude_sulfur_wt_pct", "product_sulfur_mgkg", "product_t95_c", "product_cetane_number"]) {
      const value = canonical[key];
      const base = defaults[key];
      if (!isNumber(value) || !isNumber(base) || equalCondition(value, base)) continue;
      if (other && equalCondition(other[key], value)) continue;
      if (!applied.some((item) => item.change === key)) {
        out.push(`${CONDITION_LABELS[key] ?? key}: изменение не попало в применённые сервером`);
      }
    }
  }
  return out;
}

type Parts = Record<string, unknown>;

const sameContent = (a: unknown, b: unknown): boolean => canonicalJson(a ?? null) === canonicalJson(b ?? null);

/** Часть отпечатка известна у обеих записей (null/отсутствие — неизвестно, а не «одинаково»). */
const bothKnown = (pa: Parts, pb: Parts, key: string): boolean =>
  pa[key] !== undefined && pa[key] !== null && pb[key] !== undefined && pb[key] !== null;

function requestedValue(record: RunRecord, key: string): unknown {
  return requested(record)?.[key] ?? (key === "snapshot" ? record.meta?.conditions_applied?.snapshot : undefined);
}

export interface InputExplanation {
  /** Изменения содержимого при неизменных ключах: тот же сценарий/срез по имени, но другие данные, или другая модель. */
  contentChanges: string[];
  /** Отпечатки различаются, но ни запрошенные условия, ни известные части этого не объясняют. */
  unexplained: string | null;
}

/**
 * Разбор отличий отпечатка входов на три группы: явно запрошенные изменения (inputDiff), изменения
 * содержимого под теми же ключами и действительно необъяснённые. Объекты сравниваются по содержимому.
 */
export function explainInputs(a: RunRecord, b: RunRecord, diff: DiffItem[]): InputExplanation {
  const pa = (a.meta?.input_parts ?? null) as Parts | null;
  const pb = (b.meta?.input_parts ?? null) as Parts | null;
  const requestedKeys = new Set(diff.map((item) => item.key));
  const contentChanges: string[] = [];
  let explainedDerived = requestedKeys.size > 0;
  if (pa && pb) {
    const sameScenario = sameContent(requestedValue(a, "scenario"), requestedValue(b, "scenario"));
    const sameSnapshot = sameContent(requestedValue(a, "snapshot"), requestedValue(b, "snapshot"));
    if (bothKnown(pa, pb, "scenario_sha256") && !sameContent(pa.scenario_sha256, pb.scenario_sha256) && sameScenario) {
      contentChanges.push("Содержимое или конфигурация сценария изменились при том же имени сценария");
    }
    if (bothKnown(pa, pb, "snapshot_sha256") && !sameContent(pa.snapshot_sha256, pb.snapshot_sha256) && sameSnapshot) {
      contentChanges.push("Содержимое среза данных изменилось при том же ключе среза");
    }
    if (bothKnown(pa, pb, "model") && !sameContent(pa.model, pb.model)) {
      contentChanges.push("Модель отклика заменена");
    }
    explainedDerived = explainedDerived || contentChanges.length > 0;
    // Привязка отклика и профиль тяжести выводятся из сценария, среза и модели: их расхождение
    // объяснено, если изменилось что-то из исходного; иначе это изменение под теми же ключами.
    if (!explainedDerived) {
      if (bothKnown(pa, pb, "response_binding") && !sameContent(pa.response_binding, pb.response_binding)) {
        contentChanges.push("Привязка модели отклика к срезу изменилась при тех же условиях");
      }
      if (bothKnown(pa, pb, "severity_profile") && !sameContent(pa.severity_profile, pb.severity_profile)) {
        contentChanges.push("Профиль тяжести изменился при тех же условиях");
      }
    }
  }
  const fa = a.meta?.input_fingerprint;
  const fb = b.meta?.input_fingerprint;
  const explained = requestedKeys.size > 0 || contentChanges.length > 0;
  const unexplained = fa && fb && fa !== fb && !explained
    ? "Отпечаток эффективных входов различается, но ни запрошенные условия, ни переданные части отпечатка этого не объясняют"
    : null;
  return { contentChanges, unexplained };
}

function providerKey(record: RunRecord): string {
  const provider = record.meta?.provider;
  return provider ? `${provider.provider ?? "?"}/${provider.model ?? "?"}` : "неизвестно";
}

function horizonOf(record: RunRecord): number | null {
  return record.meta?.horizon_hours ?? record.payload.decision.tradeoff?.horizon_hours ?? null;
}

function severityProfileOf(record: RunRecord): string | null {
  const block = record.payload.decision.severity;
  return block?.selected?.profile_id ?? block?.current?.profile_id ?? record.meta?.severity_profile ?? null;
}

function severityOf(record: RunRecord): number | null {
  const block = record.payload.decision.severity;
  const value = block?.selected?.index ?? record.payload.decision.severity_index;
  return isNumber(value) ? value : null;
}

function comparabilityFlags(a: RunRecord, b: RunRecord): Incomparable[] {
  const out: Incomparable[] = [];
  const sa = a.meta?.conditions_applied?.snapshot ?? a.payload.snapshot ?? null;
  const sb = b.meta?.conditions_applied?.snapshot ?? b.payload.snapshot ?? null;
  const snapA = a.meta?.input_parts?.snapshot_sha256;
  const snapB = b.meta?.input_parts?.snapshot_sha256;
  if ((sa ?? "?") !== (sb ?? "?")) {
    out.push({ key: "snapshot", text: "Срез данных различается: разницу нельзя приписывать одному изменённому условию." });
  } else if (typeof snapA === "string" && typeof snapB === "string" && snapA !== snapB) {
    out.push({ key: "snapshot", text: "Содержимое среза различается при том же ключе: показатели несопоставимы." });
  }
  const ma = a.meta?.model;
  const mb = b.meta?.model;
  const modelKnown = (m: typeof ma): boolean => Boolean(m?.response_model_sha256 && m?.training_fingerprint);
  if (!modelKnown(ma) || !modelKnown(mb)) {
    out.push({ key: "model", text: "Версия модели неизвестна у одной из записей: сопоставимость моделей не подтверждена." });
  } else if (ma!.response_model_sha256 !== mb!.response_model_sha256 || ma!.training_fingerprint !== mb!.training_fingerprint) {
    out.push({ key: "model", text: "Модели различаются: показатели прогноза несопоставимы." });
  }
  if (providerKey(a) !== providerKey(b)) {
    out.push({ key: "provider", text: `Провайдер или модель агентов различаются (${providerKey(a)} и ${providerKey(b)}).` });
  }
  const ha = horizonOf(a);
  const hb = horizonOf(b);
  if (ha === null || hb === null || Math.abs(ha - hb) > 1e-9) {
    out.push({ key: "horizon", text: ha === null || hb === null
      ? "Горизонт расчёта неизвестен у одной из записей: выпуск и стоимость за горизонт не сравниваются."
      : `Горизонт различается (${num(ha, 1)} и ${num(hb, 1)} ч): выпуск и стоимость несопоставимы.` });
  }
  const pa = severityProfileOf(a);
  const pb = severityProfileOf(b);
  if (!pa || !pb || pa !== pb) {
    out.push({ key: "severity", text: "Профиль тяжести различается или неизвестен: разница тяжести не считается." });
  }
  const ca = a.meta?.code?.commit;
  const cb = b.meta?.code?.commit;
  if (ca && cb && ca !== cb) out.push({ key: "code", text: "Записи получены разными версиями кода." });
  return out;
}

function statusText(payload: ScreenPayload): string {
  return payload.status_label || payload.decision.status;
}

function planText(payload: ScreenPayload): string {
  const plan = payload.decision.selected_plan;
  return plan ? `${plan.plan_id}${plan.changes === 0 ? " · без изменений" : ` · изменений: ${plan.changes}`}` : "нет плана";
}

function changesText(payload: ScreenPayload): string {
  if (payload.decision.status === "refuse") return "не выдавались";
  if (payload.decision.status === "hold") return "изменений нет";
  const lines = changeLines(payload);
  if (lines === null) return "перечень не передан";
  return lines.length === 0 ? "изменений нет" : lines.map(changeText).join("; ");
}

function numberRow(id: string, label: string, av: number | null, bv: number | null, digits: number,
  unit: string, comparable: boolean, note: string | null): PairRow {
  const fmt = (v: number | null) => (v === null ? "неизвестно" : `${num(v, digits)}${unit ? ` ${unit}` : ""}`);
  const both = av !== null && bv !== null;
  const changed = both ? Math.abs(av - bv) > 10 ** -(digits + 1) : null;
  let delta: string | null = null;
  let why = note;
  if (both && comparable) {
    const diff = bv - av;
    delta = `${diff > 0 ? "+" : ""}${num(diff, digits)}${unit ? ` ${unit}` : ""}`;
  } else if (both && !comparable) {
    why = note ?? "разница не считается: показатели несопоставимы";
  }
  return { id, label, a: fmt(av), b: fmt(bv), changed, delta, note: why };
}

function robustnessText(payload: ScreenPayload): string {
  const robust = payload.decision.robustness;
  if (!robust) return "не оценивалась";
  const base = `${robust.held} из ${robust.perturbations_evaluated}`;
  return robust.fragile ? `${base} · план хрупкий` : `${base} · устойчив`;
}

function needsText(payload: ScreenPayload): string {
  if (payload.decision.status !== "refuse") return "—";
  const steps = payload.explanation?.next_steps ?? [];
  if (steps.length === 0) return "перечень не передан";
  return steps.map((step) => step.need).join("; ");
}

const KIND_LABEL: Record<string, string> = {
  bad_data: "нет достоверного источника качества",
  no_feasible_plan: "нет допустимого плана",
  model_not_applicable: "режим вне области модели",
  agent_rejected: "план отклонён агентами",
  fragile_plan: "план хрупкий к отклонениям",
  tank_estimate_sensitive: "результат чувствителен к оценке резервуара",
  refused_on_data: "отказ по данным",
  refused_no_plan: "отказ: плана нет",
  source_degraded: "источник деградирован",
  sulfur_operating_margin: "тонкий запас по сере",
  plan_switched: "план заменён",
  resource_or_scenario_condition: "условие ресурса или сценария"
};

const kindText = (kind: string): string => KIND_LABEL[kind] ?? kind;

function refusalText(payload: ScreenPayload): string {
  if (payload.decision.status !== "refuse") return "—";
  const kind = payload.explanation?.kind ?? payload.decision.refusal?.kind;
  return kind ? kindText(kind) : "причина не передана";
}

function marginOf(payload: ScreenPayload): number | null {
  const warning = payload.explanation?.warnings?.find((item) => item.kind === "sulfur_operating_margin");
  return isNumber(warning?.observed_margin_mgkg) ? (warning?.observed_margin_mgkg as number) : null;
}

function warningsText(payload: ScreenPayload): string {
  const risk = (payload.explanation?.risk?.items ?? []).map((item) => item.kind);
  const warn = (payload.explanation?.warnings ?? []).map((item) => item.kind);
  const all = [...new Set([...risk, ...warn])];
  return all.length === 0 ? "нет" : all.map(kindText).join(", ");
}

export function comparePair(a: RunRecord, b: RunRecord): PairComparison {
  const pa = a.payload;
  const pb = b.payload;
  const diff = inputDiff(a, b);
  const incomparable = comparabilityFlags(a, b);
  const skip = new Set(incomparable.map((item) => item.key));
  const horizonOk = !skip.has("horizon") && !skip.has("model") && !skip.has("snapshot");
  const profileOk = !skip.has("severity") && !skip.has("horizon");
  const rows: PairRow[] = [];
  const text = (id: string, label: string, av: string, bv: string, note: string | null = null) =>
    rows.push({ id, label, a: av, b: bv, changed: av !== bv, delta: null, note });
  text("status", "Статус", statusText(pa), statusText(pb));
  text("plan", "План", planText(pa), planText(pb));
  const ca = changesText(pa);
  const cb = changesText(pb);
  text("changes", "Уставки, рецепт, присадка", ca, cb);
  rows.push(numberRow("production", "Выпуск за горизонт", pa.decision.production_t, pb.decision.production_t, 1, "т",
    horizonOk, null));
  rows.push(numberRow("cost", "Стоимость на тонну", pa.decision.cost_per_tonne, pb.decision.cost_per_tonne, 3, "у. е./т",
    horizonOk, null));
  rows.push(numberRow("severity", "Тяжесть режима", severityOf(a), severityOf(b), 3, "", profileOk,
    profileOk ? null : "профили тяжести различаются или неизвестны: разница не считается"));
  const ma = marginOf(pa);
  const mb = marginOf(pb);
  if (ma !== null || mb !== null) {
    rows.push(numberRow("margin", "Запас по сере до предела", ma, mb, 2, "мг/кг", horizonOk, null));
  }
  text("robustness", "Устойчивость", robustnessText(pa), robustnessText(pb));
  if (pa.decision.status === "refuse" || pb.decision.status === "refuse") {
    text("refusal", "Причина отказа", refusalText(pa), refusalText(pb));
    text("needs", "Что нужно измерить", needsText(pa), needsText(pb));
  }
  text("warnings", "Предупреждения", warningsText(pa), warningsText(pb));

  const decisive = rows.filter((row) => ["status", "plan", "changes"].includes(row.id));
  const answerChanged = decisive.some((row) => row.changed);
  const numericChanged = rows.filter((row) => ["production", "cost", "severity"].includes(row.id) && row.changed);
  let headline: string;
  if (answerChanged) {
    headline = `Ответ изменился: ${statusText(pa)} → ${statusText(pb)}`;
    if (statusText(pa) === statusText(pb)) headline = "Ответ изменился: другой план или другие уставки";
  } else if (numericChanged.length > 0) {
    headline = "Ответ советчика не изменился, изменились показатели";
  } else {
    headline = "Ответ не изменился: тот же статус, план и уставки";
  }
  const notes: string[] = [];
  const nondet = [a, b].some((record) => record.meta?.provider?.deterministic_policy === false);
  if (nondet) notes.push("Агенты работали на живой языковой модели: вариативность агента тоже может влиять на результат, не только изменённое условие.");
  const explanation = explainInputs(a, b, diff ?? []);
  return {
    headline, answerChanged, inputDiff: diff ?? [], inputsKnown: diff !== null,
    identicalInputs: a.meta?.input_fingerprint && b.meta?.input_fingerprint
      ? a.meta.input_fingerprint === b.meta.input_fingerprint : null,
    hiddenChanges: explanation.contentChanges, unexplained: explanation.unexplained,
    notApplied: [...notAppliedOf(b, a)], incomparable, rows, notes
  };
}
