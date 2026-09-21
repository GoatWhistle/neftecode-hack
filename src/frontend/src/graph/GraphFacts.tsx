import type { GraphEdge, GraphModel } from "./model";
import { AGENT_NAMES } from "../run/agentEvents";
import { JsonPanel } from "../ui/Json";

const VERDICT_TEXT: Record<string, string> = {
  ACCEPT: "принять план",
  REVISE: "доработать план",
  REJECT: "отклонить план",
  UNKNOWN: "данных не хватило"
};

const RISK_TEXT: Record<string, string> = {
  low: "риск низкий",
  medium: "риск средний",
  high: "риск высокий"
};

export interface GraphFactsProps {
  model: GraphModel;
  selected: string | null;
  reveal: number;
}

function WholeFacts({ model }: { model: GraphModel }) {
  const asks = model.edges.filter((edge) => edge.kind === "ask").length;
  const answers = model.edges.filter((edge) => edge.kind === "answer");
  const tools = model.edges.filter((edge) => edge.kind === "tool").length;
  const specialists = model.nodes.filter((node) => node.kind === "specialist");
  const verdicts = specialists
    .map((node) => node.verdict)
    .filter((one): one is string => one !== null);
  const worst = answers.find((edge) => edge.tone === "fail")
    ?? answers.find((edge) => edge.tone === "warn")
    ?? null;
  const rows: Array<[string, string]> = [
    ["запросов оркестратора", String(asks)],
    ["вердиктов получено", String(answers.length)],
    ["своих инструментов", String(tools)],
    ["специалистов в обмене", String(specialists.length)]
  ];
  if (verdicts.length > 0) rows.push(["вердикты", verdicts.join(" · ")]);

  return (
    <div className="gfacts__card">
      <h3 className="gfacts__name">Обмен целиком</h3>
      <p className="gfacts__role">
        {worst === null
          ? "Все опрошенные специалисты согласились с планом без возражений."
          : `Не всё прошло гладко: ${worst.label} на ходе ${worst.seq}.`}
        {" "}Нажмите на узел, чтобы оставить только его ходы.
      </p>
      <dl className="gfacts__rows">
        {rows.map(([label, value]) => (
          <div key={label} className="gfacts__row">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function NodeFacts({ model, selected }: { model: GraphModel; selected: string }) {
  const node = model.nodes.find((one) => one.id === selected);
  if (node === undefined) return null;
  const rows: Array<[string, string]> = [];
  if (node.calls > 0) rows.push(["обращений к модели", String(node.calls)]);
  if (node.tools.length > 0) rows.push(["инструментов", String(node.tools.length)]);
  if (node.verdict !== null) {
    rows.push(["вердикт", `${node.verdict} — ${VERDICT_TEXT[node.verdict] ?? "смысл не описан"}`]);
  }
  if (node.risk !== null) rows.push(["риск", RISK_TEXT[node.risk] ?? node.risk]);
  if (node.confidence !== null) {
    rows.push(["уверенность", `${Math.round(node.confidence * 10)} из 10, как передал агент`]);
  }

  return (
    <div className="gfacts__card">
      <h3 className="gfacts__name">{node.title}</h3>
      <p className="gfacts__role">{node.role}</p>
      {rows.length > 0 ? (
        <dl className="gfacts__rows">
          {rows.map(([label, value]) => (
            <div key={label} className="gfacts__row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {node.tools.length > 0 ? (
        <ul className="gfacts__tools">
          {node.tools.map((tool) => <li key={tool}><code>{tool}</code></li>)}
        </ul>
      ) : null}
      {node.events.length > 0 ? (
        <JsonPanel title={`JSON: события узла «${node.title}». Всего: ${node.events.length}`}
          value={node.events} openTo={1} />
      ) : null}
    </div>
  );
}

function EdgeLine({ edge, shown }: { edge: GraphEdge; shown: boolean }) {
  const from = AGENT_NAMES[edge.from] ?? edge.from;
  const to = AGENT_NAMES[edge.to] ?? edge.to;
  const arrow = edge.kind === "tool" ? `${from} → инструмент` : `${from} → ${to}`;
  const long = edge.detail !== null && edge.detail.length > 90;
  return (
    <li className={`gfacts__move gfacts__move--${edge.tone}${shown ? " is-shown" : ""}`}>
      <span className="gfacts__seq">{edge.seq < 10 ? `0${edge.seq}` : edge.seq}</span>
      <span className="gfacts__who">{arrow}</span>
      <span className="gfacts__what">{edge.label}</span>
      {edge.detail !== null && !long ? (
        <span className="gfacts__detail">{edge.detail}</span>
      ) : null}
      {edge.detail === null && edge.events.length === 0 ? null : (
        <details className="gfacts__more">
          <summary>{long ? "что вернулось и сырое событие" : "сырое событие"}</summary>
          {long ? <p className="gfacts__detail">{edge.detail}</p> : null}
          <JsonPanel title={`JSON хода ${edge.seq}`} value={edge.events} openTo={2} />
        </details>
      )}
    </li>
  );
}

export function GraphFacts({ model, selected, reveal }: GraphFactsProps) {
  const edges = selected === null
    ? model.edges
    : model.edges.filter((edge) => edge.from === selected || edge.to === selected);

  return (
    <aside className="gfacts" aria-live="polite">
      {selected === null ? (
        <WholeFacts model={model} />
      ) : (
        <NodeFacts model={model} selected={selected} />
      )}

      <div className="gfacts__log">
        <h4 className="gfacts__rubric">
          Ходы
          <span className="gfacts__count">{edges.length}</span>
        </h4>
        <ol className="gfacts__moves">
          {edges.map((edge) => (
            <EdgeLine key={edge.id} edge={edge} shown={edge.order < reveal} />
          ))}
        </ol>
      </div>
    </aside>
  );
}
