import type { ScreenPayload } from "../types";
import type { Lamp } from "../ui/Primitives";
import { lampOf } from "../stages";
import { hasLiveFacts } from "./StageLive";
import type { RunState, StageFacts, StageState } from "./types";

export interface RailSignal {
  lamp: Lamp;
  note: string;
  live: boolean;
}

const RUNNING: RailSignal = { lamp: "idle", note: "идёт", live: true };
const PENDING: RailSignal = { lamp: "idle", note: "ждёт", live: false };
const FAILED: RailSignal = { lamp: "fail", note: "обрыв связи", live: true };
const SKIPPED: RailSignal = { lamp: "idle", note: "не выполнялся", live: false };
export const SILENT_NOTE = "без отметок";

const SILENT: RailSignal = { lamp: "idle", note: SILENT_NOTE, live: false };

export const STATE_WORD: Record<StageState, string> = {
  pending: "ожидает",
  running: "идёт",
  done: "готово",
  skipped: "пропущено",
  failed: "обрыв связи"
};

export function marked(id: string, facts: StageFacts | undefined, events = 0): boolean {
  if (id === "agents" && events > 0) return true;
  if (hasLiveFacts(id, facts)) return true;
  return facts !== undefined && Object.keys(facts).length > 0;
}

export function outlineStateWord(id: string, state: StageState, facts: StageFacts | undefined,
                                 events = 0): string {
  if (state !== "done") return STATE_WORD[state];
  return marked(id, facts, events) ? STATE_WORD.done : SILENT_NOTE;
}

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
  if (state === "skipped") return SKIPPED;

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

  if (live) return live;
  return marked(id, run.stageFacts[id], run.agentEvents.length)
    ? { lamp: "idle", note: "отметки приняты", live: true }
    : SILENT;
}
