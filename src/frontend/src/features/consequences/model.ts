import type {
  ConsequenceApplicabilityPoint, ConsequenceEvent, ConsequencePoint, ConsequenceSeries, Consequences
} from "../../types";

export interface Segment {
  points: ConsequencePoint[];
}

/**
 * Разрывает ряд на непрерывные участки: точка без числа (value === null) не соединяется линией
 * через дыру — пропуск виден как разрыв, а не выдуманная интерполяция.
 */
export function segments(points: ConsequencePoint[]): Segment[] {
  const out: Segment[] = [];
  let current: ConsequencePoint[] = [];
  for (const point of points) {
    if (point.value === null) {
      if (current.length > 0) out.push({ points: current });
      current = [];
      continue;
    }
    current.push(point);
  }
  if (current.length > 0) out.push({ points: current });
  return out;
}

/** Пустой ряд ничего не проверил: это «нет оценки», а не пройденная проверка. */
export function worstStatus(points: ConsequencePoint[]): "pass" | "fail" | "unknown" {
  if (points.length === 0) return "unknown";
  if (points.some((p) => p.status === "fail")) return "fail";
  if (points.some((p) => p.status === "unknown")) return "unknown";
  return "pass";
}

export function defaultSeries(consequences: Consequences): ConsequenceSeries | null {
  const withFail = consequences.series.find(
    (s) => worstStatus(s.candidates.selected.points) === "fail"
  );
  return withFail ?? consequences.series[0] ?? null;
}

export interface ApplicabilityMoments {
  outside: number[];
  unknown: number[];
}

/**
 * Только явное `out_of_region` — выход из откалиброванной области (экстраполяция). Любое другое
 * значение, кроме `in_region`, — неизвестная применимость: она не доказывает экстраполяцию.
 */
export function applicabilityMoments(points: ConsequenceApplicabilityPoint[]): ApplicabilityMoments {
  return {
    outside: points.filter((p) => p.value === "out_of_region").map((p) => p.t),
    unknown: points.filter((p) => p.value !== "in_region" && p.value !== "out_of_region").map((p) => p.t)
  };
}

export function directionWord(direction: string): string {
  if (direction === "max") return "не выше";
  if (direction === "min") return "не ниже";
  return "предел";
}

const STAGE_WORD: Record<string, string> = { avt: "АВТ", hydrotreating: "гидроочистка" };

/** Короткая подпись события: что меняется и где действует. Без догадок о лаге. */
export function eventLabel(event: ConsequenceEvent): string {
  if (event.kind === "control") {
    const names = Object.entries(event.controls ?? {}).map(([k, v]) => `${k} → ${v}`).join(", ");
    return `${STAGE_WORD[event.stage ?? ""] ?? event.stage ?? "стадия"}: ${names}`;
  }
  const what = (event.changed ?? []).map((c) =>
    c === "recipe" ? "рецептура" : c === "throughput_tph" ? "выпуск" : c === "additive_dose" ? "присадка" : c
  );
  return `смешение: ${what.join(", ")}`;
}

export function originWord(origin: string): string {
  return origin === "confirmed" ? "подтверждённое ранее" : "шаг плана";
}
