import type { TraceEvent } from "../types";
import type { AgentEvent } from "../run/types";
import { Empty, Note } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { AgentCard } from "../ui/AgentCard";
import { AgenticMode } from "../ui/AgenticMode";
import { AgentDialogue } from "../ui/AgentDialogue";
import { Opinions } from "../ui/Opinions";
import { AgentFinal } from "../ui/AgentFinal";
import type { StageProps } from "./StateStage";

const ORDER = ["data", "optimizer", "lookahead", "quality", "reliability", "robustness"];

function ordered(trace: TraceEvent[]): TraceEvent[] {
  return [...trace].sort((a, b) => {
    const left = ORDER.indexOf(a.agent);
    const right = ORDER.indexOf(b.agent);
    return (left === -1 ? ORDER.length : left) - (right === -1 ? ORDER.length : right);
  });
}

export interface AgentsStageProps extends StageProps {
  events: AgentEvent[];
}

export function AgentsStage({ payload, index, state, source, events }: AgentsStageProps) {
  const agentic = payload.decision.agentic;
  const trace = ordered(payload.decision.trace ?? []);
  const vetoes = trace.reduce((acc, event) => acc + ((event["vetoes"] as unknown[] | undefined)?.length ?? 0), 0);
  const running = state === "running";

  return (
    <Section
      id="agents"
      index={index}
      state={state}
      source={source}
      title="Агенты"
      lead="Диалог оркестратора со специалистами по мере его хода: кто кого спросил, какой инструмент выбрал сам агент, что вернулось, какой вердикт и почему."
      lamp={running ? "idle" : trace.length === 0 ? "unknown" : vetoes > 0 ? "fail" : "pass"}
      lampTitle={`участников: ${trace.length}`}
    >
      <AgenticMode agentic={agentic} />

      <AgentDialogue events={events} running={running} />

      <h3 className="agents__heading">Ответы агентов</h3>
      <Opinions agentic={agentic} />
      <AgentFinal agentic={agentic} />

      {trace.length === 0 ? (
        <Empty>Сводная трасса участников не передавалась.</Empty>
      ) : (
        <>
          <h3 className="agents__heading">Сводка по участникам</h3>
          <div className="agents">
            {trace.map((event) => (
              <AgentCard key={event.agent} event={event} />
            ))}
          </div>
        </>
      )}

      <Note>
        В трассе нет ни текста промптов, ни ключей, ни скрытых рассуждений: события несут только
        сводку вызова и результата. Это решение по безопасности аудита, а не обрезанная выдача.
      </Note>

      <JsonPanel title={`JSON: полная трасса агентного слоя, ${events.length} событий`}
        value={agentic?.trace ?? payload.decision.trace} openTo={1} />
    </Section>
  );
}
