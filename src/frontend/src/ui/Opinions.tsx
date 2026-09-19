import type { AgentOpinion, Agentic } from "../types";
import { num } from "../format";
import type { Lamp } from "./Primitives";
import { Empty, Tag } from "./Primitives";
import { JsonPanel } from "./Json";

const ROLES: Record<string, string> = {
  quality: "Агент качества",
  reliability: "Агент надёжности",
  data: "Агент данных"
};

const VERDICTS: Record<string, string> = {
  ACCEPT: "принять план",
  REVISE: "пересмотреть план",
  REJECT: "отклонить план"
};

const RISK: Record<string, string> = {
  low: "низкий риск",
  medium: "средний риск",
  high: "высокий риск"
};

function toneOf(verdict: string): Lamp {
  if (verdict === "ACCEPT") return "pass";
  if (verdict === "REJECT") return "fail";
  return "unknown";
}

function Opinion({ opinion }: { opinion: AgentOpinion }) {
  const tone = toneOf(opinion.verdict);
  return (
    <article className={`opinion opinion--${tone}`}>
      <header className="opinion__head">
        <h4 className="opinion__role">{ROLES[opinion.role] ?? opinion.role}</h4>
        <Tag tone={tone}>{VERDICTS[opinion.verdict] ?? opinion.verdict}</Tag>
      </header>

      <dl className="opinion__meta">
        <div>
          <dt>Уровень риска</dt>
          <dd>{RISK[opinion.risk_level ?? ""] ?? opinion.risk_level ?? "не передан"}</dd>
        </div>
        <div>
          <dt>Уверенность</dt>
          <dd>{opinion.confidence === null ? "не передана" : num(opinion.confidence, 2)}</dd>
        </div>
      </dl>

      {opinion.reasons.length > 0 ? (
        <ul className="opinion__reasons">
          {opinion.reasons.map((reason) => (
            <li key={reason.code}>
              <p className="opinion__text">{reason.text}</p>
              <p className="opinion__code">
                код: <code>{reason.code}</code>
                {reason.candidate_id ? <> · план <code>{reason.candidate_id}</code></> : null}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>Обоснование не передавалось.</Empty>
      )}

      {opinion.proposed_constraints && opinion.proposed_constraints.length > 0 ? (
        <p className="opinion__proposal">
          Агент сам предложил ограничение:{" "}
          {opinion.proposed_constraints.map((item) => (
            <code key={`${item.type}-${item.limit}`}>
              {item.type} {item.limit} ≥ {num(item.value, 3)}
            </code>
          ))}
        </p>
      ) : null}

      <JsonPanel title={`JSON мнения «${opinion.role}»`} value={opinion} openTo={2} />
    </article>
  );
}

export function Opinions({ agentic }: { agentic: Agentic | null }) {
  const opinions = agentic?.opinions ?? [];
  if (opinions.length === 0) {
    return <Empty>Мнения агентов не передавались.</Empty>;
  }
  return (
    <div className="opinions">
      {opinions.map((opinion) => (
        <Opinion key={opinion.role} opinion={opinion} />
      ))}
    </div>
  );
}
