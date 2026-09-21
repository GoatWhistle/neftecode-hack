import type { Decision, SourceVerdict } from "./decision";
import type { Explanation, Forecast } from "./explanation";

export * from "./decision";
export * from "./explanation";

export interface TankDefault {
  id: string;
  inventory: number | null;
  on_demand: boolean;
  available: boolean;
}

export interface ScreenDefaults {
  tanks?: TankDefault[];
  product_sulfur_mgkg?: number;
  throughput_tph?: number;
  [key: string]: unknown;
}

export interface RunMeta {
  schema: string;
  created_at: string | null;
  conditions_requested: Record<string, unknown> | null;
  conditions_applied: {
    changes: Array<{ change: string; value: number | boolean; target?: string }>;
    snapshot: string | null;
    fault: string | null;
    injection: string | null;
    decision_time: string | null;
  } | null;
  input_fingerprint: string | null;
  input_parts: Record<string, unknown> | null;
  code: { commit: string | null; dirty: boolean | null; note: string | null } | null;
  model: { response_model_sha256: string | null; training_fingerprint: string | null } | null;
  provider: {
    provider: string | null;
    model: string | null;
    deterministic_policy: boolean | null;
    mode: string | null;
    outcome: string | null;
  } | null;
  horizon_hours: number | null;
  severity_profile: string | null;
}

export interface ScreenPayload {
  state: string;
  title: string;
  status_label: string;
  decision: Decision;
  explanation: Explanation;
  inventories: Record<string, number>;
  sources: SourceVerdict[];
  rule_origin: string | null;
  state_origin: string | null;
  decision_time: string | null;
  forecast: Forecast | null;
  forecast_used: boolean | null;
  defaults?: ScreenDefaults;
  applied?: Array<{ change: string; value: number | boolean; target?: string }>;
  injection?: string | null;
  snapshot?: string | null;
  binding?: Record<string, unknown> | null;
  run_meta?: RunMeta | null;
  decision_timeout_s?: number;
  agentic_state?: { mode: string; outcome: string; reason: string; note: string };
}

export interface ErrorPayload {
  state: "error";
  message: string;
}

export interface LoadingPayload {
  state: "loading";
  message: string;
}

export function isError(payload: ApiPayload): payload is ErrorPayload {
  return payload.state === "error";
}

export type ApiPayload = ScreenPayload | ErrorPayload | LoadingPayload;

export function isScreen(payload: ApiPayload): payload is ScreenPayload {
  return payload.state === "decision" || payload.state === "refusal";
}
