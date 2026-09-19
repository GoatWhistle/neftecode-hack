import type { OrchestratorAct } from "./agentActs";
import type { AgentEvent, StageFacts } from "./types";

export interface OrchMove {
  step: number | null;
  key: string;
  call: AgentEvent | null;
  tools: AgentEvent[];
  finals: AgentEvent[];
  resolutions: AgentEvent[];
  others: AgentEvent[];
}

export interface OrchChronicle {
  agent: string;
  moves: OrchMove[];
  limit: number | null;
}

export function stepLimit(agent: string, facts: StageFacts | undefined): number | null {
  const sent = facts?.budget_limits;
  if (!sent) return null;
  const key = agent === "orchestrator" ? "max_steps" : "specialist_max_calls";
  const value = sent[key];
  return typeof value === "number" && value > 0 ? value : null;
}

export function chronicle(act: OrchestratorAct, facts: StageFacts | undefined): OrchChronicle {
  const moves: OrchMove[] = [];
  const byStep = new Map<number, OrchMove>();
  for (const event of act.events) {
    const step = typeof event.step === "number" && event.step > 0 ? event.step : null;
    let move = step === null ? undefined : byStep.get(step);
    if (move === undefined) {
      move = { step, key: `move-${event.seq}`, call: null, tools: [], finals: [],
        resolutions: [], others: [] };
      moves.push(move);
      if (step !== null) byStep.set(step, move);
    }
    if (event.kind === "llm_call" && move.call === null) move.call = event;
    else if (event.kind === "tool" || event.kind === "consult") move.tools.push(event);
    else if (event.kind === "final") move.finals.push(event);
    else if (event.kind === "resolution") move.resolutions.push(event);
    else move.others.push(event);
  }
  return { agent: act.agent, moves, limit: stepLimit(act.agent, facts) };
}
