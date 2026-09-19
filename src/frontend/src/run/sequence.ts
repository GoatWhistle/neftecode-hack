import type { PhaseEvent, RunPhase, StageFacts, StageState } from "./types";

export const EARLY_STAGES = ["state", "trust", "forecast"];

export const ORDER = ["state", "trust", "forecast", "candidates", "gate", "agents", "choice", "decision"];

export function visibleCount(stages: Record<string, StageState>): number {
  let shown = 0;
  for (const id of ORDER) {
    const state = stages[id];
    shown += 1;
    if (state === undefined || state === "pending") break;
  }
  return shown;
}


export function advanceTo(current: Record<string, StageState>, id: string,
                          state: StageState): Record<string, StageState> {
  const next = { ...current };
  const target = ORDER.indexOf(id);
  if (target === -1) return { ...next, [id]: state };
  for (const earlier of ORDER.slice(0, target)) {
    const state = next[earlier];
    if (state === undefined || state === "pending" || state === "running") next[earlier] = "done";
  }
  next[id] = state;
  return next;
}

export function chainTo(current: Record<string, StageState>, id: string): string[] {
  const target = ORDER.indexOf(id);
  if (target === -1) return [id];
  const out: string[] = [];
  for (const earlier of ORDER.slice(0, target)) {
    const state = current[earlier];
    if (state === undefined || state === "pending") out.push(earlier);
  }
  out.push(id);
  return out;
}

export const LATE_STAGES = ["candidates", "gate", "choice", "decision"];

export function mergeFacts(current: Record<string, StageFacts>, id: string,
                           facts: StageFacts): Record<string, StageFacts> {
  if (Object.keys(facts).length === 0) return current;
  return { ...current, [id]: { ...(current[id] ?? {}), ...facts } };
}

export function mergePhase(phases: RunPhase[], event: PhaseEvent): RunPhase[] {
  const next: RunPhase = {
    key: event.key,
    label: event.label,
    detail: event.detail,
    state: event.state ?? "done",
    elapsedMs: Number.isFinite(event.elapsed_ms) ? event.elapsed_ms : 0
  };
  const at = phases.findIndex((item) => item.key === event.key);
  if (at === -1) return [...phases, next];
  const copy = [...phases];
  copy[at] = next;
  return copy;
}
