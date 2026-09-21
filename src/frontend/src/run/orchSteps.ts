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
  bare: boolean;
  lone: boolean;
  order: number;
}

export interface OrchChronicle {
  agent: string;
  moves: OrchMove[];
  limit: number | null;
  resumed: boolean;
  firstStep: number | null;
  total: number;
}

export function stepLimit(agent: string, facts: StageFacts | undefined): number | null {
  const sent = facts?.budget_limits;
  if (!sent) return null;
  const key = agent === "orchestrator" ? "max_steps" : "specialist_max_calls";
  const value = sent[key];
  return typeof value === "number" && value > 0 ? value : null;
}

export function chronicle(act: OrchestratorAct, facts: StageFacts | undefined,
  offset = 0): OrchChronicle {
  const moves: OrchMove[] = [];
  const byStep = new Map<number, OrchMove>();
  for (const event of act.events) {
    const step = typeof event.step === "number" && event.step > 0 ? event.step : null;
    let move = step === null ? undefined : byStep.get(step);
    if (move === undefined) {
      move = { step, key: `move-${event.seq}`, call: null, tools: [], finals: [],
        resolutions: [], others: [], bare: false, lone: false, order: 0 };
      moves.push(move);
      if (step !== null) byStep.set(step, move);
    }
    if (event.kind === "llm_call" && move.call === null) move.call = event;
    else if (event.kind === "tool" || event.kind === "consult") move.tools.push(event);
    else if (event.kind === "final") move.finals.push(event);
    else if (event.kind === "resolution") move.resolutions.push(event);
    else move.others.push(event);
  }
  for (const move of moves) {
    const blocks = move.tools.length + move.finals.length
      + move.resolutions.length + move.others.length;
    move.bare = blocks === 0;
    move.lone = blocks === 1;
  }
  moves.forEach((move, index) => {
    move.order = offset + index + 1;
  });
  const head = moves[0];
  const first = head === undefined ? null : head.order;
  return {
    agent: act.agent,
    moves,
    limit: stepLimit(act.agent, facts),
    resumed: offset > 0,
    firstStep: first,
    total: moves.length
  };
}

export function moveOffsets(acts: Array<{ kind: string; agent?: string;
  events?: AgentEvent[] }>): Map<string, number> {
  const offsets = new Map<string, number>();
  const seen = new Map<string, number>();
  for (const act of acts) {
    if (act.kind !== "orchestrator" || act.agent === undefined) continue;
    const before = seen.get(act.agent) ?? 0;
    offsets.set((act as unknown as OrchestratorAct).key, before);
    const steps = new Set<number>();
    let loose = 0;
    for (const event of act.events ?? []) {
      const step = typeof event.step === "number" && event.step > 0 ? event.step : null;
      if (step === null) loose += 1;
      else steps.add(step);
    }
    seen.set(act.agent, before + steps.size + loose);
  }
  return offsets;
}
