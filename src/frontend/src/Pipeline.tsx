import type { ScreenPayload } from "./types";
import type { AgentEvent, StageSource, StageState } from "./run/types";
import { StateStage } from "./stages/StateStage";
import { TrustStage } from "./stages/TrustStage";
import { ForecastStage } from "./stages/ForecastStage";
import { CandidatesStage } from "./stages/CandidatesStage";
import { GateStage } from "./stages/GateStage";
import { AgentsStage } from "./stages/AgentsStage";
import { ChoiceStage } from "./stages/ChoiceStage";
import { DecisionStage } from "./stages/DecisionStage";

const SOURCE_TEXT: Record<StageSource, string> = {
  server: "отметка сервера: этот блок собран при разборе условий",
  payload: "раскрыт из уже посчитанного payload — это не длительность расчёта этапа"
};

export interface PipelineProps {
  payload: ScreenPayload;
  stateOf: (id: string) => StageState;
  sources: Record<string, StageSource>;
  agentEvents: AgentEvent[];
}

export function Pipeline({ payload, stateOf, sources, agentEvents }: PipelineProps) {
  const label = (id: string): string | undefined => {
    const source = sources[id];
    if (!source || stateOf(id) !== "done") return undefined;
    return SOURCE_TEXT[source];
  };

  const common = (id: string) => ({
    payload,
    state: stateOf(id),
    source: label(id)
  });

  return (
    <>
      <StateStage {...common("state")} index={1} />
      <TrustStage {...common("trust")} index={2} />
      <ForecastStage {...common("forecast")} index={3} />
      <CandidatesStage {...common("candidates")} index={4} />
      <GateStage {...common("gate")} index={5} />
      <AgentsStage {...common("agents")} index={6} events={agentEvents} />
      <ChoiceStage {...common("choice")} index={7} />
      <DecisionStage {...common("decision")} index={8} />
    </>
  );
}
