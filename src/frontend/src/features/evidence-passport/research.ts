import type { RunMeta } from "../../types";

/**
 * Версионированная сводка уже выполненного исследования. Сборщик —
 * `src/neftecode/infrastructure/artifacts/research_summary.py`; числа переносятся из
 * `research/forecast/*.json` без округления. Здесь — только проверка формы и привязка к записи.
 */
export const RESEARCH_SUMMARY_SCHEMA = "neftecode.research-summary/1";

export interface ResearchMethod {
  method: string;
  mae_mgkg: number;
  rmse_mgkg: number;
  exceed_upper: number;
  two_sided_coverage: number;
  mean_upper_margin_mgkg: number;
  mean_interval_width_mgkg: number;
  point_exceedance_recall: number;
}

export interface ResearchSummary {
  schema: typeof RESEARCH_SUMMARY_SCHEMA;
  study_id: string;
  kind: "research_result";
  sources: Array<{ path: string; sha256: string; schema_version: string | null }>;
  protocol: string;
  document: string;
  subject: { quantity: string; object: string; target: string; unit: string; reference: string };
  period: string;
  total_targets: number;
  paired_targets: number;
  baseline: ResearchMethod;
  winner: ResearchMethod;
  paired_mae_difference: { value_mgkg: number; ci95_mgkg: [number, number]; bootstrap_draws: number; seed: number };
  goal: {
    metric: string;
    max: number;
    kind: "research_target";
    reference: string;
    met_by_winner: boolean;
    met_by_baseline: boolean;
  };
  selection: {
    frozen_before_period: boolean;
    changed_by_result: boolean;
    evidence_sha256: string | null;
    development_end: string | null;
  };
  model_link: { evaluation_fingerprint: string | null; declared_fingerprints: string[]; note: string };
  interpretation: string | null;
}

export class ResearchSummaryError extends Error {}

const METRICS = [
  "mae_mgkg", "rmse_mgkg", "exceed_upper", "two_sided_coverage", "mean_upper_margin_mgkg",
  "mean_interval_width_mgkg", "point_exceedance_recall"
] as const;

function obj(value: unknown, where: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ResearchSummaryError(`${where}: ожидался объект`);
  }
  return value as Record<string, unknown>;
}

function str(value: unknown, where: string): string {
  if (typeof value !== "string" || value.length === 0) throw new ResearchSummaryError(`${where}: ожидалась строка`);
  return value;
}

function strOrNull(value: unknown, where: string): string | null {
  if (value === null) return null;
  return str(value, where);
}

function finite(value: unknown, where: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ResearchSummaryError(`${where}: неизвестное или неконечное число`);
  }
  return value;
}

function count(value: unknown, where: string): number {
  const number = finite(value, where);
  if (!Number.isInteger(number) || number < 0) throw new ResearchSummaryError(`${where}: ожидалось целое ≥ 0`);
  return number;
}

function share(value: unknown, where: string): number {
  const number = finite(value, where);
  if (number < 0 || number > 1) throw new ResearchSummaryError(`${where}: доля вне [0; 1]`);
  return number;
}

function bool(value: unknown, where: string): boolean {
  if (typeof value !== "boolean") throw new ResearchSummaryError(`${where}: ожидалось да/нет`);
  return value;
}

function method(raw: unknown, where: string): ResearchMethod {
  const item = obj(raw, where);
  const out: Record<string, unknown> = { method: str(item.method, `${where}.method`) };
  for (const key of METRICS) {
    const value = finite(item[key], `${where}.${key}`);
    out[key] = key === "exceed_upper" || key === "two_sided_coverage" || key === "point_exceedance_recall"
      ? share(value, `${where}.${key}`) : value;
  }
  return out as unknown as ResearchMethod;
}

/**
 * Адаптер для общего импорта протокола: принимает неизвестный JSON, возвращает типизированную
 * сводку или бросает ResearchSummaryError. Неизвестная версия схемы не «подгоняется» под текущую.
 */
export function validateResearchSummary(raw: unknown): ResearchSummary {
  const root = obj(raw, "сводка");
  if (root.schema !== RESEARCH_SUMMARY_SCHEMA) {
    throw new ResearchSummaryError(`сводка: неподдерживаемая схема «${String(root.schema)}» (нужна ${RESEARCH_SUMMARY_SCHEMA})`);
  }
  if (root.kind !== "research_result") throw new ResearchSummaryError("сводка: неизвестный вид результата");
  if (!Array.isArray(root.sources) || root.sources.length === 0) {
    throw new ResearchSummaryError("сводка: нет исходных артефактов");
  }
  const sources = root.sources.map((item, index) => {
    const source = obj(item, `sources[${index}]`);
    const sha = str(source.sha256, `sources[${index}].sha256`);
    if (!/^[0-9a-f]{64}$/.test(sha)) throw new ResearchSummaryError(`sources[${index}].sha256: не SHA-256`);
    return {
      path: str(source.path, `sources[${index}].path`), sha256: sha,
      schema_version: strOrNull(source.schema_version ?? null, `sources[${index}].schema_version`)
    };
  });
  const subject = obj(root.subject, "subject");
  const diff = obj(root.paired_mae_difference, "paired_mae_difference");
  if (!Array.isArray(diff.ci95_mgkg) || diff.ci95_mgkg.length !== 2) {
    throw new ResearchSummaryError("paired_mae_difference.ci95_mgkg: ожидалась пара чисел");
  }
  const low = finite(diff.ci95_mgkg[0], "ci95[0]");
  const high = finite(diff.ci95_mgkg[1], "ci95[1]");
  if (low > high) throw new ResearchSummaryError("paired_mae_difference.ci95_mgkg: границы перепутаны");
  const goal = obj(root.goal, "goal");
  if (goal.kind !== "research_target") throw new ResearchSummaryError("goal: цель должна быть исследовательской");
  const selection = obj(root.selection, "selection");
  const link = obj(root.model_link, "model_link");
  if (!Array.isArray(link.declared_fingerprints)) {
    throw new ResearchSummaryError("model_link.declared_fingerprints: ожидался список");
  }
  const total = count(root.total_targets, "total_targets");
  const paired = count(root.paired_targets, "paired_targets");
  if (paired > total) throw new ResearchSummaryError("paired_targets больше total_targets");
  const baseline = method(root.baseline, "baseline");
  const winner = method(root.winner, "winner");
  const max = share(goal.max, "goal.max");
  const metByWinner = bool(goal.met_by_winner, "goal.met_by_winner");
  const metByBaseline = bool(goal.met_by_baseline, "goal.met_by_baseline");
  if (metByWinner !== winner.exceed_upper <= max || metByBaseline !== baseline.exceed_upper <= max) {
    throw new ResearchSummaryError("goal: отметка достижения цели противоречит числам сводки");
  }
  return {
    schema: RESEARCH_SUMMARY_SCHEMA,
    study_id: str(root.study_id, "study_id"),
    kind: "research_result",
    sources,
    protocol: str(root.protocol, "protocol"),
    document: str(root.document, "document"),
    subject: {
      quantity: str(subject.quantity, "subject.quantity"), object: str(subject.object, "subject.object"),
      target: str(subject.target, "subject.target"), unit: str(subject.unit, "subject.unit"),
      reference: str(subject.reference, "subject.reference")
    },
    period: str(root.period, "period"),
    total_targets: total,
    paired_targets: paired,
    baseline,
    winner,
    paired_mae_difference: {
      value_mgkg: finite(diff.value_mgkg, "paired_mae_difference.value_mgkg"),
      ci95_mgkg: [low, high],
      bootstrap_draws: count(diff.bootstrap_draws, "bootstrap_draws"),
      seed: count(diff.seed, "seed")
    },
    goal: {
      metric: str(goal.metric, "goal.metric"), max, kind: "research_target",
      reference: str(goal.reference, "goal.reference"), met_by_winner: metByWinner, met_by_baseline: metByBaseline
    },
    selection: {
      frozen_before_period: bool(selection.frozen_before_period, "selection.frozen_before_period"),
      changed_by_result: bool(selection.changed_by_result, "selection.changed_by_result"),
      evidence_sha256: strOrNull(selection.evidence_sha256 ?? null, "selection.evidence_sha256"),
      development_end: strOrNull(selection.development_end ?? null, "selection.development_end")
    },
    model_link: {
      evaluation_fingerprint: strOrNull(link.evaluation_fingerprint ?? null, "model_link.evaluation_fingerprint"),
      declared_fingerprints: link.declared_fingerprints.map((item, index) => str(item, `declared_fingerprints[${index}]`)),
      note: str(link.note, "model_link.note")
    },
    interpretation: root.interpretation === null || root.interpretation === undefined
      ? null : str(root.interpretation, "interpretation")
  };
}

/** Слот протокола: отсутствие поля (старый протокол) и null — честное «сводки нет». */
export function researchSlot(raw: unknown): ResearchSummary | null {
  if (raw === undefined || raw === null) return null;
  return validateResearchSummary(raw);
}

export type ModelLink = "evaluated" | "declared" | "other" | "unknown";

/** Относится ли исследование к модели этой записи. Сравнивается отпечаток записи, не текущий сервер. */
export function modelLink(summary: ResearchSummary, meta: RunMeta | null | undefined): ModelLink {
  const own = meta?.model?.training_fingerprint ?? null;
  if (own === null) return "unknown";
  if (summary.model_link.evaluation_fingerprint === own) return "evaluated";
  if (summary.model_link.declared_fingerprints.includes(own)) return "declared";
  return "other";
}
