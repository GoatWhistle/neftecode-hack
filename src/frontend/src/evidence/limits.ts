import type { GateCheck, ScreenPayload } from "../types";

export type LimitDirection = "max" | "min" | "unknown";

export interface LimitRow {
  id: string;
  direction: LimitDirection;
  times: number;
  observed: number | null;
  limit: number | null;
  margin: number | null;
  atHours: number | null;
  status: string;
}

const DIRECTION: Record<string, LimitDirection> = {
  "quality.sulfur_mgkg": "max",
  "quality.t95_c": "max",
  "quality.cetane_number": "min",
  "quality.density_min_kgm3": "min",
  "quality.density_max_kgm3": "max"
};

function directionOf(id: string): LimitDirection {
  return DIRECTION[id] ?? "unknown";
}

function marginOf(observed: number, limit: number, direction: LimitDirection): number | null {
  if (direction === "max") return limit - observed;
  if (direction === "min") return observed - limit;
  return null;
}

function worseStatus(a: string, b: string): string {
  const rank: Record<string, number> = { fail: 3, unknown: 2, pass: 1 };
  return (rank[b] ?? 0) > (rank[a] ?? 0) ? b : a;
}

export function limitRows(payload: ScreenPayload | null): LimitRow[] {
  const checks: GateCheck[] = payload?.decision.gate?.checks ?? [];
  if (checks.length === 0) return [];
  const byId = new Map<string, GateCheck[]>();
  for (const check of checks) {
    const list = byId.get(check.constraint_id);
    if (list) list.push(check);
    else byId.set(check.constraint_id, [check]);
  }
  const rows: LimitRow[] = [];
  byId.forEach((group, id) => {
    const direction = directionOf(id);
    let worst: { margin: number; check: GateCheck } | null = null;
    let status = "pass";
    for (const check of group) {
      status = worseStatus(status, check.status);
      const observed = check.observed;
      const limit = check.limit;
      if (typeof observed !== "number" || typeof limit !== "number") continue;
      const margin = marginOf(observed, limit, direction);
      if (margin === null) continue;
      if (worst === null || margin < worst.margin) worst = { margin, check };
    }
    rows.push({
      id,
      direction,
      times: group.length,
      observed: worst ? (worst.check.observed as number) : null,
      limit: worst ? (worst.check.limit as number) : null,
      margin: worst ? worst.margin : null,
      atHours: worst ? worst.check.time_hours ?? null : null,
      status
    });
  });
  return rows.sort((a, b) => {
    if (a.margin === null) return 1;
    if (b.margin === null) return -1;
    return a.margin - b.margin;
  });
}

export function limitsSummary(payload: ScreenPayload | null): { checks: number; unique: number } | null {
  const checks = payload?.decision.gate?.checks ?? [];
  if (checks.length === 0) return null;
  return { checks: checks.length, unique: new Set(checks.map((item) => item.constraint_id)).size };
}
