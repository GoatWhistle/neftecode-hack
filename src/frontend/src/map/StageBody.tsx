import type { ScreenPayload } from "../types";
import type { AgentEvent, StageFacts, StageState } from "../run/types";
import { lampOf } from "../stages";
import { hasLiveFacts, StageLive } from "../run/StageLive";
import { AgentDialogue } from "../ui/AgentDialogue";
import { StateStage } from "../stages/StateStage";
import { TrustStage } from "../stages/TrustStage";
import { CandidatesStage } from "../stages/CandidatesStage";
import { ForecastStage } from "../stages/ForecastStage";
import { ChoiceStage } from "../stages/ChoiceStage";
import { GateStage } from "../stages/GateStage";
import { AgentsStage } from "../stages/AgentsStage";
import { DecisionStage } from "../stages/DecisionStage";

const WAITING: Record<string, string> = {
  forecast: "Расчёт за горизонтом в этом прогоне не выполнялся: в сценарии не задан горизонт или запас реакции.",
  agents: "Оркестратор ещё не обращался к специалистам.",
  decision: "Решение собирается после того, как агенты закончат."
};

export interface StageBodyProps {
  id: string;
  index: number;
  state: StageState;
  payload: ScreenPayload | null;
  facts: StageFacts | undefined;
  agentEvents: AgentEvent[];
  elapsedMs: number;
  lastFrameAt: number | null;
}

export function StageBody({ id, index, state, payload, facts, agentEvents, elapsedMs, lastFrameAt }: StageBodyProps) {
  if (payload) {
    const signal = lampOf(id, payload);
    const common = { payload, index, state, lamp: signal.lamp, lampTitle: signal.title, bare: true };
    if (id === "state") return <StateStage {...common} />;
    if (id === "trust") return <TrustStage {...common} />;
    if (id === "candidates") return <CandidatesStage {...common} />;
    if (id === "forecast") return <ForecastStage {...common} />;
    if (id === "choice") return <ChoiceStage {...common} />;
    if (id === "gate") return <GateStage {...common} />;
    if (id === "decision") return <DecisionStage {...common} />;
    if (id === "agents") {
      return (
        <AgentsStage
          {...common}
          events={agentEvents}
          facts={facts}
          elapsedMs={elapsedMs}
          lastFrameAt={lastFrameAt}
        />
      );
    }
    return null;
  }

  const live = state === "pending" ? undefined : facts;
  const hasLive = hasLiveFacts(id, live);

  return (
    <div className="stage__body stage__body--bare">
      {id === "agents" && state !== "pending" ? (
        <AgentDialogue
          events={agentEvents}
          running={state === "running"}
          facts={live}
          agentic={null}
          elapsedMs={elapsedMs}
          lastFrameAt={lastFrameAt}
        />
      ) : (
        <StageLive id={id} facts={live} />
      )}
      {!hasLive && id !== "agents" ? (
        <p className="outline__hint">
          {state === "pending"
            ? "Данные этого этапа ещё не передавались."
            : (WAITING[id] ?? "Данные этого этапа ещё не передавались.")}
        </p>
      ) : null}
      {hasLive ? (
        <p className="outline__hint outline__hint--partial">
          Это отметки сервера по ходу расчёта. Полные числа этапа раскроются, когда придёт решение.
        </p>
      ) : null}
    </div>
  );
}
