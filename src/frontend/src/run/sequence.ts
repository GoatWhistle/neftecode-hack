import { STAGES } from "../stages";
import type { PhaseEvent, RunPhase, StageState } from "./types";

export const EARLY_STAGES = ["state", "trust", "forecast"];

export const ORDER = ["state", "trust", "forecast", "candidates", "gate", "agents", "choice", "decision"];

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

export const LATE_STAGES = ["candidates", "gate", "choice", "decision"];

export function mergePhase(phases: RunPhase[], event: PhaseEvent): RunPhase[] {
  const next: RunPhase = {
    key: event.key,
    label: event.label,
    detail: event.detail,
    state: event.state ?? "done",
    elapsedMs: event.elapsed_ms
  };
  const at = phases.findIndex((item) => item.key === event.key);
  if (at === -1) return [...phases, next];
  const copy = [...phases];
  copy[at] = next;
  return copy;
}

export function scrollTo(id: string, reduced: boolean): void {
  const node = document.getElementById(id);
  if (!node) return;
  node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

export function settled(): Record<string, StageState> {
  const out: Record<string, StageState> = {};
  for (const stage of STAGES) out[stage.id] = "done";
  return out;
}
