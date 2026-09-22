import type { ScreenPayload } from "../types";
import type { RecordInfo } from "./hydrate";

export type StageState = "pending" | "running" | "done" | "skipped" | "failed";

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

export type RunStatus = "idle" | "running" | "done" | "failed" | "stopped";

/** P5: предварительный результат ядра до окончания агентного этапа — не окончательный ответ. */
export interface CoreEvent {
  phase: "preliminary";
  decision_id: string | null;
  status: string | null;
  plan_id: string | null;
  core_s: number;
  deadline_s?: number;
  max_llm_calls?: number;
  note: string;
  elapsedMs: number;
}

export interface AgentEvent {
  seq: number;
  agent: string;
  step: number;
  kind: string;
  tool_name?: string;
  tool_input_summary?: string;
  tool_result_summary?: string;
  tool_result_full?: string;
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
  available?: boolean;
  lookahead_hours?: number;
  min_reaction_hours?: number;
  hours_to_violation?: number;
  stock_ends_at_hours?: number;
  switched?: boolean;
  examined?: number;
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
  query: string | null;
  phases: RunPhase[];
  stages: Record<string, StageState>;
  stageSource: Record<string, StageSource>;
  stageAt: Record<string, number>;
  stageFacts: Record<string, StageFacts>;
  agentEvents: AgentEvent[];
  core: CoreEvent | null;
  payload: ScreenPayload | null;
  elapsedMs: number;
  serverMs: number | null;
  lastFrameAt: number | null;
  error: string | null;
  live: boolean;
  record: RecordInfo | null;
}

export const EMPTY_RUN: RunState = {
  status: "idle",
  query: null,
  phases: [],
  stages: {},
  stageSource: {},
  stageAt: {},
  stageFacts: {},
  agentEvents: [],
  core: null,
  payload: null,
  elapsedMs: 0,
  serverMs: null,
  lastFrameAt: null,
  error: null,
  live: false,
  record: null
};

export function stageStateOf(run: RunState, id: string): StageState {
  return run.stages[id] ?? "pending";
}
