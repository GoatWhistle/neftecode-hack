import type { EdgeKind, MapEdge } from "./graph";
import { MAP_EDGES } from "./graph";
import type { MapColumns } from "./layout";
import { directionOf, rowOf } from "./layout";
import type { NodeRect, NodeRects } from "./useNodeRects";
import {
  backPath,
  backStub,
  betweenRows,
  exitSideStub,
  exitStub,
  headOf,
  LANE,
  loopPath,
  midOf,
  pathLength,
  round,
  sameRowFlow,
  toPath,
  wrapLabel
} from "./wireGeometry";

export type LabelAnchor = "middle" | "start" | "end";

export interface Wire {
  id: string;
  kind: EdgeKind;
  from: string;
  to: string;
  path: string;
  length: number;
  head: { x: number; y: number; angle: number };
  label?: string;
  labelLines?: string[];
  labelAt?: { x: number; y: number };
  labelAnchor?: LabelAnchor;
  labelDy?: number;
}

const FLOW_SHIFT: Record<string, number> = {
  "e-decision-hold": -LANE,
  "e-decision-recommend": LANE
};

function pointsFor(
  edge: MapEdge,
  rects: Record<string, NodeRect>,
  columns: MapColumns
): Array<[number, number]> | null {
  const from = rects[edge.from];
  const to = rects[edge.to];
  if (!from || !to) return null;
  if (edge.kind === "loop") return loopPath(from);
  if (edge.kind === "back") return columns === 1 ? backStub(from) : backPath(from, to);
  if (edge.kind === "exit") {
    return columns === 1 ? exitSideStub(from) : exitStub(from);
  }
  const rowA = rowOf(edge.from, columns);
  const rowB = rowOf(edge.to, columns);
  const ltr = directionOf(edge.from, columns) === "ltr";
  if (rowA && rowB && rowA.key === rowB.key) {
    return columns === 1 ? betweenRows(from, to) : sameRowFlow(from, to, ltr, FLOW_SHIFT[edge.id] ?? 0);
  }
  return betweenRows(from, to);
}

function labelOf(edge: MapEdge, points: Array<[number, number]>, columns: MapColumns): Pick<
  Wire,
  "labelAt" | "labelAnchor" | "labelDy" | "labelLines"
> {
  if (edge.kind === "exit") {
    const tail = points[points.length - 1] as [number, number];
    return { labelAt: { x: round(tail[0]), y: round(tail[1]) }, labelDy: 13 };
  }
  if (edge.kind === "loop") {
    const outer = points[1] as [number, number];
    return {
      labelAt: { x: round(outer[0] - 2), y: round(outer[1]) },
      labelAnchor: "start",
      labelDy: 14,
      labelLines: wrapLabel(edge.label ?? "")
    };
  }
  if (edge.kind === "back" && columns === 1) {
    const outer = points[1] as [number, number];
    return {
      labelAt: { x: round(outer[0] - 2), y: round(outer[1]) },
      labelAnchor: "start",
      labelDy: 14,
      labelLines: wrapLabel(edge.label ?? "")
    };
  }
  return { labelAt: midOf(points), labelDy: -6 };
}

export function buildWires(measured: NodeRects, columns: MapColumns = 4): Wire[] {
  const out: Wire[] = [];
  for (const edge of MAP_EDGES) {
    const points = pointsFor(edge, measured.rects, columns);
    if (!points || points.length < 2) continue;
    const wire: Wire = {
      id: edge.id,
      kind: edge.kind,
      from: edge.from,
      to: edge.to,
      path: toPath(points),
      length: Math.max(1, Math.round(pathLength(points))),
      head: headOf(points)
    };
    if (edge.label) {
      wire.label = edge.label;
      Object.assign(wire, labelOf(edge, points, columns));
    }
    out.push(wire);
  }
  return out;
}
