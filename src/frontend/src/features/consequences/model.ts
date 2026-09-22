import type { ConsequenceApplicabilityPoint, ConsequencePoint, ConsequenceSeries, Consequences } from "../../types";

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

export function worstStatus(points: ConsequencePoint[]): "pass" | "fail" | "unknown" {
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

export function outOfRegionMoments(points: ConsequenceApplicabilityPoint[]): number[] {
  return points.filter((p) => p.value !== "in_region").map((p) => p.t);
}

export function directionWord(direction: string): string {
  if (direction === "max") return "не выше";
  if (direction === "min") return "не ниже";
  return "предел";
}
