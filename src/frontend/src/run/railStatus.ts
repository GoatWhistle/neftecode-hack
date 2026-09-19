import type { ScreenPayload } from "../types";
import type { Lamp } from "../ui/Primitives";
import { lampOf } from "../stages";
import type { RunState, StageFacts, StageState } from "./types";

export interface RailSignal {
  lamp: Lamp;
  note: string;
  live: boolean;
}

const RUNNING: RailSignal = { lamp: "idle", note: "идёт", live: true };
const PENDING: RailSignal = { lamp: "idle", note: "ждёт", live: false };
const FAILED: RailSignal = { lamp: "fail", note: "отказ", live: true };
const SILENT: RailSignal = { lamp: "idle", note: "без отметок", live: false };

function factSignal(id: string, facts: StageFacts | undefined): RailSignal | null {
  if (!facts) return null;
  if (id === "trust") {
    if (typeof facts.usable === "boolean") {
      return facts.usable
        ? { lamp: "pass", note: "источник годен", live: true }
        : { lamp: "fail", note: "источника нет", live: true };
    }
    return null;
  }
  if (id === "candidates") {
    if (typeof facts.feasible === "number") {
      return facts.feasible > 0
        ? { lamp: "pass", note: `допустимых ${facts.feasible}`, live: true }
        : { lamp: "fail", note: "допустимых нет", live: true };
    }
    return null;
  }
  if (id === "gate") {
    if (typeof facts.feasible === "boolean") {
      return facts.feasible
        ? { lamp: "pass", note: "проверки пройдены", live: true }
        : { lamp: "fail", note: "проверки не пройдены", live: true };
    }
    return null;
  }
  if (id === "choice") {
    if (typeof facts.plan_id === "string") {
      return { lamp: "pass", note: `план ${facts.plan_id}`, live: true };
    }
    return null;
  }
  if (id === "state") {
    const stock = facts.inventories;
    if (stock && Object.keys(stock).length > 0) {
      return { lamp: "pass", note: "запасы приняты", live: true };
    }
    return null;
  }
  return null;
}

export function railSignal(run: RunState, payload: ScreenPayload | null, id: string): RailSignal {
  const state: StageState = run.stages[id] ?? "pending";
  if (state === "failed") return FAILED;
  if (state === "pending") return PENDING;

  const live = factSignal(id, run.stageFacts[id]);
  if (state === "running") {
    if (live) return live;
    if (id === "agents" && run.agentEvents.length > 0) {
      return { lamp: "idle", note: `идёт, событий ${run.agentEvents.length}`, live: true };
    }
    return RUNNING;
  }

  if (payload) {
    const { lamp } = lampOf(id, payload);
    if (lamp === "fail") return { lamp, note: "не прошёл", live: true };
    if (lamp === "unknown") return { lamp, note: "неполно", live: true };
    return { lamp, note: "пройден", live: true };
  }

  return live ?? SILENT;
}
