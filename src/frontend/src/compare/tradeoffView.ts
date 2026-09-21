import type { TradeoffMap, TradeoffPoint } from "../types";

export interface Axis {
  min: number;
  max: number;
  degenerate: boolean;
}

export function axisOf(values: number[]): Axis {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return { min: 0, max: 1, degenerate: true };
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  if (hi - lo < 1e-9) {
    const pad = Math.max(Math.abs(lo) * 0.05, 0.5);
    return { min: lo - pad, max: hi + pad, degenerate: true };
  }
  const pad = (hi - lo) * 0.08;
  return { min: lo - pad, max: hi + pad, degenerate: false };
}

export function scale(value: number, axis: Axis, size: number, invert = false): number {
  const t = (value - axis.min) / (axis.max - axis.min);
  return (invert ? 1 - t : t) * size;
}

export function pointStatus(point: TradeoffPoint): string {
  const tags: string[] = [];
  if (point.selected) tags.push("выбран");
  if (point.is_hold) tags.push("текущий режим");
  tags.push(point.on_front ? "на фронте" : `доминируется ${point.dominated_by ?? "другим планом"}`);
  return tags.join(" · ");
}

export function distinctFront(map: TradeoffMap): TradeoffPoint[] {
  return map.points.filter((point) => point.on_front);
}

export type MapVerdict =
  | { kind: "empty"; text: string }
  | { kind: "unknown"; text: string }
  | { kind: "single"; text: string }
  | { kind: "many"; text: string };

export function mapVerdict(map: TradeoffMap): MapVerdict {
  if (map.status === "empty") return { kind: "empty", text: "Допустимых вариантов в исследованном пуле нет: сравнивать нечего." };
  if (map.status === "unknown_metrics") {
    return { kind: "unknown", text: "У допустимых вариантов не хватает показателей для полного сравнения по трём осям." };
  }
  if (map.pool.distinct_points <= 1) {
    return { kind: "single", text: "Все допустимые варианты дают одинаковые показатели: график не показывает альтернатив." };
  }
  if (map.pool.front_distinct <= 1) {
    return {
      kind: "single",
      text: "Фронт выродился в одну точку: один вариант не хуже остальных по всем осям сразу, компромисса между целями нет."
    };
  }
  return { kind: "many", text: `Недоминируемых вариантов по трём осям: ${map.pool.front_distinct}.` };
}
