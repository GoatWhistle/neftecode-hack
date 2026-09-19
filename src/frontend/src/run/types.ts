import type { ScreenPayload } from "../types";

export type StageState = "pending" | "running" | "done" | "failed";

export type StageSource = "server" | "payload";

export interface PhaseEvent {
  key: string;
  label: string;
  detail: string;
  state?: StageState;
  elapsed_ms: number;
}

export interface RunPhase {
  key: string;
  label: string;
  detail: string;
  state: StageState;
  elapsedMs: number;
}

export type RunStatus = "idle" | "running" | "done" | "failed";

export interface AgentEvent {
  seq: number;
  agent: string;
  step: number;
  kind: string;
  tool_name?: string;
  tool_input_summary?: string;
  tool_result_summary?: string;
  decision?: string;
  reason_codes?: string[];
  candidate_ids?: string[];
  latency_ms?: number;
  provider?: string;
  model?: string;
  usage?: Record<string, number>;
  elapsedMs: number;
}

export interface RunState {
  status: RunStatus;
  phases: RunPhase[];
  stages: Record<string, StageState>;
  stageSource: Record<string, StageSource>;
  agentEvents: AgentEvent[];
  payload: ScreenPayload | null;
  elapsedMs: number;
  serverMs: number | null;
  error: string | null;
  live: boolean;
}

export const EMPTY_RUN: RunState = {
  status: "idle",
  phases: [],
  stages: {},
  stageSource: {},
  agentEvents: [],
  payload: null,
  elapsedMs: 0,
  serverMs: null,
  error: null,
  live: false
};

export function stageStateOf(run: RunState, id: string): StageState {
  return run.stages[id] ?? "pending";
}
