import type { AgentEvent, CoreEvent, RunState, StageState } from "./types";
import { EMPTY_RUN } from "./types";
import type { RunRecord } from "./record";
import { advanceTo, LATE_STAGES, mergeFacts, mergePhase, ORDER, stageRan } from "./sequence";

export interface RecordInfo {
  recordedAt: string;
  exportedAt: string | null;
  provider: string | null;
  model: string | null;
  runId: string;
  label: string;
}

export function recordInfoOf(record: RunRecord, exportedAt: string | null): RecordInfo {
  return {
    recordedAt: record.recorded_at,
    exportedAt,
    provider: record.meta?.provider?.provider ?? record.payload.decision.agentic?.provider ?? null,
    model: record.meta?.provider?.model ?? record.payload.decision.agentic?.model ?? null,
    runId: record.run_id,
    label: record.label
  };
}

/**
 * Итоговое состояние запуска, восстановленное из записи без обращений к серверу и без пауз:
 * результат доступен сразу, повтор событий — отдельным действием.
 */
export function hydrateRun(record: RunRecord, info: RecordInfo): RunState {
  let stages: Record<string, StageState> = {};
  let stageFacts: RunState["stageFacts"] = {};
  let stageSource: RunState["stageSource"] = {};
  let stageAt: RunState["stageAt"] = {};
  let phases: RunState["phases"] = [];
  const agentEvents: AgentEvent[] = [];
  let core: CoreEvent | null = null;
  let elapsedMs = 0;
  let serverMs: number | null = null;
  for (const frame of record.events) {
    const item = frame as Record<string, unknown>;
    if (frame.kind === "phase") {
      const phase = item.phase as never;
      phases = mergePhase(phases, phase);
      elapsedMs = (phase as { elapsed_ms: number }).elapsed_ms ?? elapsedMs;
    } else if (frame.kind === "stage") {
      const id = item.stage as string;
      const state = ((item.state as StageState | undefined) ?? "done") as StageState;
      stageFacts = mergeFacts(stageFacts, id, (item.facts as never) ?? {});
      stageSource = { ...stageSource, [id]: "server" };
      stageAt = { ...stageAt, [id]: item.elapsedMs as number };
      stages = advanceTo(stages, id, state === "running" ? "done" : state);
      elapsedMs = item.elapsedMs as number;
    } else if (frame.kind === "agent") {
      agentEvents.push(item.event as AgentEvent);
    } else if (frame.kind === "core") {
      core = item.core as CoreEvent;
    } else if (frame.kind === "screen") {
      serverMs = item.elapsedMs as number;
      elapsedMs = serverMs;
    }
  }
  for (const id of ORDER) {
    if (stages[id] === undefined || stages[id] === "running") {
      const late = LATE_STAGES.includes(id);
      stages = { ...stages, [id]: late && !stageRan(id, record.payload) ? "skipped" : "done" };
      if (late && stageSource[id] === undefined) stageSource = { ...stageSource, [id]: "payload" };
    }
  }
  return {
    ...EMPTY_RUN,
    status: "done",
    query: record.query,
    phases,
    stages,
    stageSource,
    stageAt,
    stageFacts,
    agentEvents,
    core,
    payload: record.payload,
    elapsedMs,
    serverMs,
    live: false,
    record: info
  };
}
