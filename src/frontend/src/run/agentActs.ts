import type { AgentEvent } from "./types";
import { CONSTRAINT_TEXT, CONSTRAINT_VOCABULARY } from "./agentVocab";

export interface ConstraintPick {
  type: string;
  label: string;
  proposed: boolean;
  value: string | null;
}

export interface OpinionDigest {
  verdict: string | null;
  riskLevel: string | null;
  confidence: number | null;
  confidenceSent: boolean;
  constraints: Array<{ type: string; limit: string | null; value: number | null }>;
  preferred: string[];
  candidateVerdicts: Record<string, string>;
  truncated: boolean;
}

export interface ConsultAct {
  kind: "consult";
  key: string;
  seq: number;
  role: string;
  index: number;
  candidateIds: string[];
  focus: string | null;
  inputRaw: string | null;
  tools: AgentEvent[];
  llmCalls: AgentEvent[];
  finals: AgentEvent[];
  resolution: AgentEvent | null;
  opinion: OpinionDigest | null;
  vetoed: string[];
  reasonCodes: string[];
  elapsedMs: number;
}

export interface BreakAct {
  kind: "guard" | "fallback" | "override";
  key: string;
  seq: number;
  event: AgentEvent;
  elapsedMs: number;
}

export interface ToolStep {
  step: number;
  tools: AgentEvent[];
  llmCalls: AgentEvent[];
}

export interface OrchestratorAct {
  kind: "orchestrator";
  key: string;
  seq: number;
  agent: string;
  events: AgentEvent[];
  elapsedMs: number;
}

export type AgentAct = ConsultAct | BreakAct | OrchestratorAct;

function roleOf(event: AgentEvent): string {
  return event.tool_name === "ask_reliability_agent" ? "reliability" : "quality";
}

function readFocus(summary: string | undefined): string | null {
  if (!summary) return null;
  try {
    const parsed = JSON.parse(summary) as Record<string, unknown>;
    const focus = parsed["focus"];
    return typeof focus === "string" && focus.length > 0 ? focus : null;
  } catch {
    const match = /"focus"\s*:\s*"([^"]*)/.exec(summary);
    const found = match?.[1];
    return found !== undefined && found.length > 0 ? found : null;
  }
}

function digest(event: AgentEvent | null): OpinionDigest | null {
  if (!event) return null;
  const raw = event.tool_result_summary;
  if (!raw) return { verdict: null, riskLevel: null, confidence: null, confidenceSent: false,
    constraints: [], preferred: [], candidateVerdicts: {}, truncated: false };
  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    parsed = null;
  }
  if (parsed === null) {
    const verdict = event.decision ? event.decision.split(":")[1] ?? null : null;
    return { verdict, riskLevel: null, confidence: null, confidenceSent: false, constraints: [],
      preferred: [], candidateVerdicts: {}, truncated: true };
  }
  const confidence = parsed["confidence"];
  const constraints = Array.isArray(parsed["proposed_constraints"])
    ? (parsed["proposed_constraints"] as Array<Record<string, unknown>>).map((item) => ({
        type: String(item["type"] ?? ""),
        limit: typeof item["limit"] === "string" ? item["limit"] : null,
        value: typeof item["value"] === "number" ? item["value"] : null
      }))
    : [];
  const preferred = Array.isArray(parsed["preferred_candidates"])
    ? (parsed["preferred_candidates"] as unknown[]).map((item) => String(item))
    : [];
  const verdicts: Record<string, string> = {};
  const rawVerdicts = parsed["candidate_verdicts"];
  if (rawVerdicts && typeof rawVerdicts === "object") {
    for (const [id, value] of Object.entries(rawVerdicts as Record<string, unknown>)) {
      verdicts[id] = String(value);
    }
  }
  return {
    verdict: typeof parsed["verdict"] === "string" ? parsed["verdict"] : null,
    riskLevel: typeof parsed["risk_level"] === "string" ? parsed["risk_level"] : null,
    confidence: typeof confidence === "number" ? confidence : null,
    confidenceSent: typeof confidence === "number",
    constraints,
    preferred,
    candidateVerdicts: verdicts,
    truncated: false
  };
}

export function buildActs(events: AgentEvent[]): AgentAct[] {
  const acts: AgentAct[] = [];
  let consult: ConsultAct | null = null;
  let consults = 0;

  const close = (): void => {
    consult = null;
  };

  for (const event of events) {
    if (event.kind === "guard" || event.kind === "fallback") {
      if (event.kind === "fallback") close();
      acts.push({ kind: event.kind, key: `${event.kind}-${event.seq}`, seq: event.seq, event,
        elapsedMs: event.elapsedMs });
      continue;
    }
    if (event.kind === "consult") {
      consults += 1;
      consult = {
        kind: "consult",
        key: `consult-${event.seq}`,
        seq: event.seq,
        role: roleOf(event),
        index: consults,
        candidateIds: event.candidate_ids ?? [],
        focus: readFocus(event.tool_input_summary),
        inputRaw: event.tool_input_summary ?? null,
        tools: [],
        llmCalls: [],
        finals: [],
        resolution: null,
        opinion: null,
        vetoed: [],
        reasonCodes: [],
        elapsedMs: event.elapsedMs
      };
      acts.push(consult);
      continue;
    }
    if (consult === null && event.kind === "resolution" && event.decision === "rank_overrides_choice") {
      acts.push({ kind: "override", key: `override-${event.seq}`, seq: event.seq, event,
        elapsedMs: event.elapsedMs });
      continue;
    }
    if (consult !== null && event.kind === "resolution") {
      consult.resolution = event;
      consult.opinion = digest(event);
      consult.vetoed = event.candidate_ids ?? [];
      consult.reasonCodes = event.reason_codes ?? [];
      close();
      continue;
    }
    if (consult !== null && event.agent === consult.role) {
      if (event.kind === "tool") consult.tools.push(event);
      else if (event.kind === "llm_call") consult.llmCalls.push(event);
      else if (event.kind === "final") consult.finals.push(event);
      continue;
    }
    if (consult !== null && event.agent === "orchestrator") close();
    const last = acts[acts.length - 1];
    if (last && last.kind === "orchestrator" && last.agent === event.agent) {
      last.events.push(event);
      continue;
    }
    acts.push({ kind: "orchestrator", key: `act-${event.seq}`, seq: event.seq, agent: event.agent,
      events: [event], elapsedMs: event.elapsedMs });
  }
  return acts;
}

export function constraintPicks(proposed: OpinionDigest["constraints"]): ConstraintPick[] {
  const byType = new Map<string, { limit: string | null; value: number | null }>();
  for (const item of proposed) byType.set(item.type, { limit: item.limit, value: item.value });
  return CONSTRAINT_VOCABULARY.map((type) => {
    const hit = byType.get(type);
    const parts: string[] = [];
    if (hit?.limit) parts.push(hit.limit);
    if (hit && hit.value !== null) parts.push(String(hit.value));
    return {
      type,
      label: CONSTRAINT_TEXT[type] ?? type,
      proposed: hit !== undefined,
      value: parts.length > 0 ? parts.join(" ") : null
    };
  });
}

export function toolSteps(act: ConsultAct): ToolStep[] {
  const order: number[] = [];
  const byStep = new Map<number, ToolStep>();
  const take = (event: AgentEvent): ToolStep => {
    const step = typeof event.step === "number" ? event.step : 0;
    let hit = byStep.get(step);
    if (hit === undefined) {
      hit = { step, tools: [], llmCalls: [] };
      byStep.set(step, hit);
      order.push(step);
    }
    return hit;
  };
  for (const call of act.llmCalls) take(call).llmCalls.push(call);
  for (const tool of act.tools) take(tool).tools.push(tool);
  return order.sort((a, b) => a - b).map((step) => byStep.get(step) as ToolStep);
}
