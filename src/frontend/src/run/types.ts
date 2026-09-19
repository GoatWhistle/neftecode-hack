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

export interface StageFacts {
  inventories?: Record<string, number>;
  sources?: Array<Record<string, unknown>>;
  usable?: boolean;
  primary?: string;
  forecast?: unknown;
  evaluated?: number;
  rounds?: number;
  feasible?: number | boolean;
  checks?: number;
  plan_id?: string;
  alternatives?: number;
  provider?: string | null;
  model?: string | null;
  deterministic_policy?: boolean;
  budget_limits?: Record<string, number>;
}

export interface RunState {
  status: RunStatus;
  phases: RunPhase[];
  stages: Record<string, StageState>;
  stageSource: Record<string, StageSource>;
  stageFacts: Record<string, StageFacts>;
  agentEvents: AgentEvent[];
  payload: ScreenPayload | null;
  elapsedMs: number;
  serverMs: number | null;
  lastFrameAt: number | null;
  error: string | null;
  live: boolean;
}

export const EMPTY_RUN: RunState = {
  status: "idle",
  phases: [],
  stages: {},
  stageSource: {},
  stageFacts: {},
  agentEvents: [],
  payload: null,
  elapsedMs: 0,
  serverMs: null,
  lastFrameAt: null,
  error: null,
  live: false
};

export function stageStateOf(run: RunState, id: string): StageState {
  return run.stages[id] ?? "pending";
}
