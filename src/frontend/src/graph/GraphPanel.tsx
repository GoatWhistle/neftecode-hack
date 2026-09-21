import { useMemo, useState } from "react";
import type { AgentEvent } from "../run/types";
import type { Agentic } from "../types";
import { buildGraph } from "./model";
import { AgentGraph, useLiveReveal } from "./AgentGraph";
import { GraphFacts } from "./GraphFacts";
import { Empty, Note } from "../ui/Primitives";

export interface GraphPanelProps {
  events: AgentEvent[];
  agentic: Agentic | null;
  running: boolean;
  selectedPlanId?: string | null;
}

function toneWord(kind: string): string {
  if (kind === "ask") return "запрос";
  if (kind === "answer") return "вердикт";
  if (kind === "tool") return "инструмент";
  return "итог";
}

export function GraphPanel({ events, agentic, running, selectedPlanId = null }: GraphPanelProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const model = useMemo(
    () => buildGraph(events, agentic, selectedPlanId),
    [events, agentic, selectedPlanId]
  );
  const reveal = useLiveReveal(model.steps, !running);
  const head = model.edges[reveal - 1] ?? null;
  const live = running || reveal < model.steps;

  if (model.absent !== null) {
    return <Empty>{model.absent}</Empty>;
  }

  const specialists = model.nodes.filter((node) => node.kind === "specialist").length;

  if (model.steps === 0 || specialists === 0) {
    return (
      <Note>
        Обмена между агентами не было: оркестратор не консультировался со специалистами.
        Это не означает, что допустимых планов не нашлось — при подтверждении текущего
        режима или удержании плана оркестратор вправе не спрашивать специалистов. Схема
        рисуется только там, где есть кого и о чём спрашивать; сами ходы оркестратора
        целиком показаны ниже, в «Ходе диалога».
      </Note>
    );
  }

  return (
    <div className="agmap">
      <div className="agmap__canvas">
        <div className={`agmap__stat${live ? " is-live" : ""}`} role="status" aria-live="polite">
          <span className="agmap__dot" aria-hidden="true" />
          <span className="agmap__stat-text">
            {live && head !== null
              ? `${toneWord(head.kind)} ${reveal} из ${model.steps}: ${head.label}`
              : `обменов: ${model.steps}`}
          </span>
        </div>
        <AgentGraph model={model} selected={selected} onSelect={setSelected}
          reveal={reveal} live={live} />
        <ul className="agmap__key" aria-label="Обозначения">
          <li className="agmap__key-item agmap__key-item--ask">запрос оркестратора</li>
          <li className="agmap__key-item agmap__key-item--pass">принял</li>
          <li className="agmap__key-item agmap__key-item--warn">просил доработать</li>
          <li className="agmap__key-item agmap__key-item--fail">отклонил</li>
          <li className="agmap__key-item agmap__key-item--tool">свой инструмент</li>
        </ul>
      </div>
      <p className="agmap__narrow">
        Для схемы нужен широкий экран: на узкой полосе подписи узлов сливаются. Все те же
        обмены перечислены ниже списком ходов, в том же порядке.
      </p>
      <GraphFacts model={model} selected={selected} reveal={reveal} />
    </div>
  );
}
