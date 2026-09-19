import { visibleCount } from "./sequence";
import { STAGES } from "../stages";
import type { AgentEvent, StageFacts, StageState } from "./types";
import { hasLiveFacts, StageLive } from "./StageLive";
import { outlineStateWord } from "./railStatus";
import { AgentDialogue } from "../ui/AgentDialogue";

const WAITING: Record<string, string> = {
  forecast: "Расчёт за горизонтом в этом прогоне не выполнялся: в сценарии не задан горизонт или запас реакции.",
  agents: "Оркестратор ещё не обращался к специалистам.",
  decision: "Решение собирается после того, как агенты закончат."
};

export interface StageOutlineProps {
  stateOf: (id: string) => StageState;
  factsOf: (id: string) => StageFacts | undefined;
  agentEvents: AgentEvent[];
  stages: Record<string, StageState>;
  elapsedMs: number;
  lastFrameAt: number | null;
}

export function StageOutline({ stateOf, factsOf, agentEvents, stages, elapsedMs, lastFrameAt }: StageOutlineProps) {
  const shown = visibleCount(stages);
  return (
    <>
      {STAGES.slice(0, shown).map((stage, position) => {
        const state = stateOf(stage.id);
        const facts = state === "pending" ? undefined : factsOf(stage.id);
        const hasLive = hasLiveFacts(stage.id, facts);
        return (
          <section
            key={stage.id}
            id={stage.id}
            className={`stage stage--outline stage--${state}`}
            data-band={position + 1}
            aria-busy={state === "running"}
          >
            <header className="stage__head stage__head--outline">
              <span className="stage__step">{position + 1}</span>
              <h2 className="stage__title">{stage.label}</h2>
              <span className={`stage__state stage__state--${state}`}>
                {outlineStateWord(stage.id, state, facts, agentEvents.length)}
              </span>
            </header>
            {stage.id === "agents" && state !== "pending" ? (
              <AgentDialogue
                events={agentEvents}
                running={state === "running"}
                facts={facts}
                agentic={null}
                elapsedMs={elapsedMs}
                lastFrameAt={lastFrameAt}
              />
            ) : (
              <StageLive id={stage.id} facts={facts} />
            )}
            {!hasLive && stage.id !== "agents" ? (
              <p className="outline__hint">
                {state === "pending"
                  ? "Данные этого этапа ещё не передавались."
                  : (WAITING[stage.id] ?? "Данные этого этапа ещё не передавались.")}
              </p>
            ) : null}
            {hasLive ? (
              <p className="outline__hint outline__hint--partial">
                Это отметки сервера по ходу расчёта. Полные числа этапа раскроются, когда придёт решение.
              </p>
            ) : null}
          </section>
        );
      })}
    </>
  );
}
