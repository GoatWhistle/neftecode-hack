import type { SeverityFactors, TraceEvent } from "../types";
import type { AgentEvent, StageFacts } from "../run/types";
import { Empty, Note } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { AgentCard } from "../ui/AgentCard";
import { AgenticMode } from "../ui/AgenticMode";
import { AgentDialogue } from "../ui/AgentDialogue";
import { Opinions } from "../ui/Opinions";
import { AgentFinal } from "../ui/AgentFinal";
import { SeverityBars } from "../ui/SeverityBars";
import type { StageProps } from "./StateStage";

const ORDER = ["data", "optimizer", "lookahead", "quality", "reliability", "robustness"];

function ordered(trace: TraceEvent[]): TraceEvent[] {
  return [...trace].sort((a, b) => {
    const left = ORDER.indexOf(a.agent);
    const right = ORDER.indexOf(b.agent);
    return (left === -1 ? ORDER.length : left) - (right === -1 ? ORDER.length : right);
  });
}

function severityOf(trace: TraceEvent[]): SeverityFactors | null {
  for (const event of trace) {
    const factors = event["severity_factors"] as SeverityFactors | undefined;
    if (factors) return factors;
  }
  return null;
}

export interface AgentsStageProps extends StageProps {
  events: AgentEvent[];
  facts: StageFacts | undefined;
  elapsedMs: number;
  lastFrameAt: number | null;
}

export function AgentsStage({ payload, index, state, source, lamp, lampTitle, bare, events, facts, elapsedMs, lastFrameAt }: AgentsStageProps) {
  const agentic = payload.decision.agentic;
  const trace = ordered(payload.decision.trace ?? []);
  const severity = severityOf(trace);
  const running = state === "running";
  const opinionCount = agentic?.opinions?.length ?? 0;

  return (
    <Section
      id="agents"
      index={index}
      state={state}
      source={source}
      title="Агенты"
      lead="Диалог оркестратора со специалистами по мере его хода: кто кого спросил, какой инструмент выбрал сам агент, что вернулось, какой вердикт и почему."
      lamp={running ? "idle" : lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      <div className="agents__stage">
        <section className="agents__sec">
          <h3 className="agents__heading">Режим работы</h3>
          <AgenticMode agentic={agentic} />
        </section>

        <section className="agents__sec">
          <h3 className="agents__heading">
            Ход диалога
            {events.length > 0 ? <span className="agents__count">{events.length}</span> : null}
          </h3>
          <p className="agents__lead">
            Кто к кому обратился, какой инструмент выбрал сам агент и чем закончился каждый ход.
          </p>
          <AgentDialogue events={events} running={running} facts={facts} agentic={agentic}
            elapsedMs={elapsedMs} lastFrameAt={lastFrameAt} />
        </section>

        <section className="agents__sec">
          <h3 className="agents__heading">
            Ответы агентов
            {opinionCount > 0 ? <span className="agents__count">{opinionCount}</span> : null}
          </h3>
          <p className="agents__lead">
            Каждый специалист отвечает на своём участке: вердикт, риск, уверенность, затем обоснования
            с кодами причин.
          </p>
          <Opinions agentic={agentic} />
        </section>

        <section className="agents__sec">
          <AgentFinal agentic={agentic} />
        </section>

        <section className="agents__sec">
          <h3 className="agents__heading">
            Сводка по участникам
            {trace.length > 0 ? <span className="agents__count">{trace.length}</span> : null}
          </h3>
          {trace.length === 0 ? (
            <Empty>Сводная трасса участников не передавалась.</Empty>
          ) : (
            <>
              <p className="agents__lead">
                Что каждый участник проверил и чем закончил. Высота карточки — по её содержимому;
                разбор раскрывается на месте.
              </p>
              <div className="agents">
                {trace.map((event) => (
                  <AgentCard key={event.agent} event={event} />
                ))}
              </div>
              {severity ? <SeverityBars factors={severity} /> : null}
            </>
          )}
        </section>

        <Note>
          В трассе нет ни текста промптов, ни ключей, ни скрытых рассуждений: события несут только
          сводку вызова и результата. Это решение по безопасности аудита, а не обрезанная выдача.
        </Note>

        <JsonPanel title={`JSON: полная трасса агентного слоя. Событий: ${events.length}`}
          value={agentic?.trace ?? payload.decision.trace} openTo={1} />
      </div>
    </Section>
  );
}
