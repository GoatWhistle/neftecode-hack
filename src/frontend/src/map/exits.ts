import type { ScreenPayload } from "../types";

const EXIT_BY_KIND: Record<string, string> = {
  data: "trust",
  no_feasible_plan: "candidates",
  computation_error: "candidates",
  final_recheck_failed: "gate",
  mandatory_robustness_failed: "gate",
  agent_rejected: "agents",
  weak_response_failed: "agents"
};

export const EXIT_EDGE_BY_NODE: Record<string, string> = {
  trust: "x-trust",
  candidates: "x-candidates",
  gate: "x-gate",
  agents: "x-agents"
};

export function exitNodeOf(kind: string | null | undefined): string {
  if (!kind) return "decision";
  return EXIT_BY_KIND[kind] ?? "decision";
}

export function refusalKindOf(payload: ScreenPayload | null): string | null {
  const refusal = payload?.decision.refusal;
  if (!refusal) return null;
  return typeof refusal.kind === "string" ? refusal.kind : null;
}

export function activeExitEdge(payload: ScreenPayload | null): string | null {
  if (!payload || payload.decision.status !== "refuse") return null;
  const node = exitNodeOf(refusalKindOf(payload));
  return EXIT_EDGE_BY_NODE[node] ?? null;
}
