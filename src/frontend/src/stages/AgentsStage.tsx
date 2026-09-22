import type { ScreenPayload, SeverityFactors, TraceEvent } from "../types";
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
import { GraphPanel } from "../graph/GraphPanel";
import { Fold, modeHint } from "../graph/Fold";
import "../styles/graph.css";
import type { StageProps } from "./StateStage";

const ORDER = ["data", "optimizer", "lookahead", "quality", "reliability", "robustness"];

function ordered(trace: TraceEvent[]): TraceEvent[] {
  return [...trace].sort((a, b) => {
    const left = ORDER.indexOf(a.agent);
    const right = ORDER.indexOf(b.agent);
    return (left === -1 ? ORDER.length : left) - (right === -1 ? ORDER.length : right);
  });
}

function liveProvider(events: AgentEvent[]): { provider: string | null; model: string | null; calls: number } {
  let provider: string | null = null;
  let model: string | null = null;
  let calls = 0;
  for (const event of events) {
    if (event.kind !== "llm_call") continue;
    calls += 1;
    if (event.provider) provider = event.provider;
    if (event.model) model = event.model;
  }
  return { provider, model, calls };
}

function severityOf(trace: TraceEvent[]): SeverityFactors | null {
  for (const event of trace) {
    const factors = event["severity_factors"] as SeverityFactors | undefined;
    if (factors) return factors;
  }
  return null;
}

export interface AgentsStageProps extends Omit<StageProps, "payload"> {
  payload: ScreenPayload | null;
  events: AgentEvent[];
  facts: StageFacts | undefined;
  elapsedMs: number;
  lastFrameAt: number | null;
}

export function AgentsStage({ payload, index, state, source, lamp, lampTitle, bare, events, facts, elapsedMs, lastFrameAt }: AgentsStageProps) {
  const agentic = payload?.decision.agentic;
  const trace = ordered(payload?.decision.trace ?? []);
  const severity = severityOf(trace);
  const running = state === "running";
  const opinionCount = agentic?.opinions?.length ?? 0;
  const live = liveProvider(events);
  const modeFold = running && agentic === undefined
    ? live.model === null
      ? "идёт прогон, модель ещё не отвечала"
      : `идёт прогон · ${live.model} · вызовов: ${live.calls}`
    : modeHint(agentic ?? null);

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
        <Fold title="Режим работы" hint={modeFold}>
          <AgenticMode agentic={agentic ?? null} agenticState={payload?.agentic_state}
            live={live} />
        </Fold>

        <section className="agents__sec">
          <h3 className="agents__heading">
            Карта обмена
          </h3>
          <p className="agents__lead">
            Схема прогона: оркестратор слева, специалисты на своих дорожках. Стрелка к специалисту —
            запрос оркестратора, стрелка обратно — вердикт. Рядом с каждым узлом перечислены
            инструменты, которые агент выбрал сам. Связи появляются по мере прихода событий.
            Нажмите на узел, чтобы оставить только его ходы.
          </p>
          <GraphPanel
            events={events}
            agentic={agentic ?? null}
            running={running}
            selectedPlanId={payload?.decision.selected_plan?.plan_id ?? null}
          />
        </section>

        <Fold title="Ход диалога" hint="кто кого спросил, каким инструментом и чем закончил ход">
          <p className="agents__lead">
            Кто к кому обратился, какой инструмент выбрал сам агент и чем закончился каждый ход.
          </p>
          <AgentDialogue events={events} running={running} facts={facts} agentic={agentic ?? null}
            elapsedMs={elapsedMs} lastFrameAt={lastFrameAt} />
        </Fold>

        {opinionCount > 0 ? (
          <Fold title="Ответы агентов" hint="вердикт, риск и обоснования каждого специалиста">
            <p className="agents__lead">
              Каждый специалист отвечает на своём участке: вердикт, риск, уверенность, затем обоснования
              с кодами причин.
            </p>
            <Opinions agentic={agentic ?? null} />
          </Fold>
        ) : null}

        {agentic ? (
          <Fold title="Итог агентного слоя" hint="к чему пришли агенты и на чём сошлись">
            <AgentFinal agentic={agentic} />
          </Fold>
        ) : null}

        {trace.length === 0 ? (
          running ? null : (
            <Fold title="Сводка по участникам" hint="сводная трасса участников не передавалась">
              <Empty>Сводная трасса участников не передавалась.</Empty>
            </Fold>
          )
        ) : (
          <Fold title="Сводка по участникам" hint="что каждый участник проверил и чем закончил">
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
          </Fold>
        )}

        <Note>
          В трассе нет ни текста промптов, ни ключей, ни скрытых рассуждений: события несут только
          сводку вызова и результата. Это решение по безопасности аудита, а не обрезанная выдача.
        </Note>

        <JsonPanel title={`JSON: полная трасса агентного слоя. Событий: ${events.length}`}
          value={agentic?.trace ?? payload?.decision.trace ?? events} openTo={1} />
      </div>
    </Section>
  );
}
