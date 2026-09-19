import type { ScreenPayload } from "./types";
import type { AgentEvent, StageFacts, StageSource, StageState } from "./run/types";
import { visibleCount } from "./run/sequence";
import { lampOf } from "./stages";
import { StateStage } from "./stages/StateStage";
import { TrustStage } from "./stages/TrustStage";
import { ForecastStage } from "./stages/ForecastStage";
import { CandidatesStage } from "./stages/CandidatesStage";
import { GateStage } from "./stages/GateStage";
import { AgentsStage } from "./stages/AgentsStage";
import { ChoiceStage } from "./stages/ChoiceStage";
import { DecisionStage } from "./stages/DecisionStage";

const SOURCE_TEXT: Record<StageSource, string> = {
  server: "отметка сервера по ходу расчёта",
  payload: "раскрыт из уже посчитанного payload — это не длительность расчёта этапа"
};

export interface PipelineProps {
  payload: ScreenPayload;
  stateOf: (id: string) => StageState;
  sources: Record<string, StageSource>;
  agentEvents: AgentEvent[];
  stages: Record<string, StageState>;
  stageFacts: Record<string, StageFacts>;
  elapsedMs: number;
}

export function Pipeline({ payload, stateOf, sources, agentEvents, stages, stageFacts, elapsedMs }: PipelineProps) {
  const shown = visibleCount(stages);
  const label = (id: string): string | undefined => {
    const source = sources[id];
    if (!source || stateOf(id) !== "done") return undefined;
    return SOURCE_TEXT[source];
  };

  const common = (id: string) => {
    const signal = lampOf(id, payload);
    return {
      payload,
      state: stateOf(id),
      source: label(id),
      lamp: signal.lamp,
      lampTitle: signal.title
    };
  };

  return (
    <>
      {shown >= 1 ? <StateStage {...common("state")} index={1} /> : null}
      {shown >= 2 ? <TrustStage {...common("trust")} index={2} /> : null}
      {shown >= 3 ? <ForecastStage {...common("forecast")} index={3} /> : null}
      {shown >= 4 ? <CandidatesStage {...common("candidates")} index={4} /> : null}
      {shown >= 5 ? <GateStage {...common("gate")} index={5} /> : null}
      {shown >= 6 ? <AgentsStage {...common("agents")} index={6} events={agentEvents} facts={stageFacts["agents"]} elapsedMs={elapsedMs} /> : null}
      {shown >= 7 ? <ChoiceStage {...common("choice")} index={7} /> : null}
      {shown >= 8 ? <DecisionStage {...common("decision")} index={8} /> : null}
    </>
  );
}
