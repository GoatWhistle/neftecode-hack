import { STAGES } from "../stages";
import type { AgentEvent, StageState } from "./types";
import { AGENT_NAMES, KIND_TEXT, summarize } from "./agentEvents";

const STATE_TEXT: Record<StageState, string> = {
  pending: "ожидает",
  running: "идёт",
  done: "готово",
  failed: "отказ"
};

export interface StageOutlineProps {
  stateOf: (id: string) => StageState;
  agentEvents: AgentEvent[];
}

function AgentFeed({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return <p className="outline__hint">Оркестратор ещё не обращался к специалистам.</p>;
  }
  const recent = events.slice(-6);
  return (
    <ol className="outline__feed">
      {recent.map((event) => (
        <li key={event.seq} className="outline__event">
          <span className="outline__who">{AGENT_NAMES[event.agent] ?? event.agent}</span>
          <span className="outline__kind">{KIND_TEXT[event.kind] ?? event.kind}</span>
          <span className="outline__what">{summarize(event)}</span>
        </li>
      ))}
    </ol>
  );
}

export function StageOutline({ stateOf, agentEvents }: StageOutlineProps) {
  return (
    <>
      {STAGES.map((stage, position) => {
        const state = stateOf(stage.id);
        return (
          <section
            key={stage.id}
            id={stage.id}
            className={`stage stage--outline stage--${state}`}
            data-band={position + 1}
            aria-busy={state === "running"}
          >
            <header className="stage__head">
              <span className="stage__index">{position + 1}</span>
              <h2 className="stage__title">{stage.label}</h2>
              <span className={`stage__state stage__state--${state}`}>{STATE_TEXT[state]}</span>
            </header>
            {stage.id === "agents" && state !== "pending" ? <AgentFeed events={agentEvents} /> : null}
            {state === "pending" ? (
              <p className="outline__hint">Данные этого этапа ещё не передавались.</p>
            ) : null}
          </section>
        );
      })}
    </>
  );
}
