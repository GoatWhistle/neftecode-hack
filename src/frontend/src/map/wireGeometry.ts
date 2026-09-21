import type { NodeRect } from "./useNodeRects";

export const INSET = 2;
export const ARROW = 8;
export const LOOP_REACH = 30;
export const EXIT_DROP = 44;
export const LANE = 16;

export function round(value: number): number {
  return Math.round(value * 10) / 10;
}

export function pathLength(points: Array<[number, number]>): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1] as [number, number];
    const here = points[i] as [number, number];
    total += Math.abs(here[0] - prev[0]) + Math.abs(here[1] - prev[1]);
  }
  return total;
}

export function toPath(points: Array<[number, number]>): string {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${round(point[0])} ${round(point[1])}`)
    .join(" ");
}

export function headOf(points: Array<[number, number]>): { x: number; y: number; angle: number } {
  const last = points[points.length - 1] as [number, number];
  const prev = (points[points.length - 2] ?? last) as [number, number];
  const angle = (Math.atan2(last[1] - prev[1], last[0] - prev[0]) * 180) / Math.PI;
  return { x: round(last[0]), y: round(last[1]), angle: round(angle) };
}

export function wrapLabel(label: string): string[] {
  const words = label.split(" ");
  if (words.length < 2) return [label];
  const mid = Math.ceil(words.length / 2);
  return [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
}

export function midOf(points: Array<[number, number]>): { x: number; y: number } {
  let best = 0;
  let bestSpan = -1;
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1] as [number, number];
    const here = points[i] as [number, number];
    const span = Math.abs(here[0] - prev[0]);
    if (span > bestSpan) {
      bestSpan = span;
      best = i;
    }
  }
  const a = points[best - 1] as [number, number];
  const b = points[best] as [number, number];
  return { x: round((a[0] + b[0]) / 2), y: round((a[1] + b[1]) / 2) };
}

export function sameRowFlow(
  from: NodeRect,
  to: NodeRect,
  ltr: boolean,
  shift = 0
): Array<[number, number]> {
  const y1 = round(from.top + from.height / 2 + shift);
  const y2 = round(to.top + to.height / 2);
  const x1 = ltr ? from.left + from.width + INSET : from.left - INSET;
  const far = ltr ? to.left - INSET : to.left + to.width + INSET;
  const x2 = ltr ? Math.max(x1 + ARROW, far) : Math.min(x1 - ARROW, far);
  if (Math.abs(y1 - y2) < 2) {
    return [
      [x1, y1],
      [x2, y1]
    ];
  }
  const turn = round((x1 + x2) / 2);
  return [
    [x1, y1],
    [turn, y1],
    [turn, y2],
    [x2, y2]
  ];
}

export function betweenRows(from: NodeRect, to: NodeRect): Array<[number, number]> {
  const startX = round(from.left + from.width * 0.28);
  const startY = from.top + from.height + INSET;
  const endX = round(to.left + to.width * 0.28);
  const endY = to.top - INSET;
  if (Math.abs(startX - endX) < 2) {
    return [
      [endX, startY],
      [endX, endY]
    ];
  }
  const turn = round((startY + endY) / 2);
  return [
    [startX, startY],
    [startX, turn],
    [endX, turn],
    [endX, endY]
  ];
}

export function loopPath(rect: NodeRect): Array<[number, number]> {
  const edge = round(rect.left + rect.width);
  const out = round(edge + LOOP_REACH);
  const upper = round(rect.top + rect.height * 0.26);
  const lower = round(rect.top + rect.height * 0.74);
  return [
    [edge + INSET, lower],
    [out, lower],
    [out, upper],
    [edge + INSET + ARROW, upper]
  ];
}

export function exitStub(from: NodeRect): Array<[number, number]> {
  const x = round(from.left + from.width * 0.5);
  const top = round(from.top + from.height + INSET);
  return [
    [x, top],
    [x, round(top + EXIT_DROP)]
  ];
}

export function exitSideStub(from: NodeRect): Array<[number, number]> {
  const y = round(from.top + from.height * 0.5);
  const edge = round(from.left + from.width);
  return [
    [edge + INSET, y],
    [round(edge + LOOP_REACH), y]
  ];
}

export function backPath(from: NodeRect, to: NodeRect): Array<[number, number]> {
  const startX = round(from.left + from.width * 0.72);
  const startY = from.top - INSET;
  const endX = round(to.left + to.width * 0.72);
  const endY = to.top + to.height + INSET;
  const turn = round(startY - LANE);
  return [
    [startX, startY],
    [startX, turn],
    [endX, turn],
    [endX, endY]
  ];
}

export function backStub(from: NodeRect): Array<[number, number]> {
  const edge = round(from.left + from.width);
  const out = round(edge + LOOP_REACH);
  const upper = round(from.top + from.height * 0.34);
  const lower = round(from.top + from.height * 0.66);
  return [
    [edge + INSET, lower],
    [out, lower],
    [out, upper],
    [edge + INSET + ARROW, upper]
  ];
}
