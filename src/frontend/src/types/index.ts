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
