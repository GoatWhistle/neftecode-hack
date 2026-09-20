import type { AgentOpinion, Agentic } from "../types";
import { num } from "../format";
import { constraintTypeText, limitText } from "../run/orchRead";
import type { Lamp } from "./Primitives";
import { Empty, LampDot, Tag } from "./Primitives";
import { JsonPanel } from "./Json";

const ROLES: Record<string, string> = {
  quality: "Агент качества",
  reliability: "Агент надёжности",
  data: "Агент данных"
};

const SCOPES: Record<string, string> = {
  quality: "свойства продукта",
  reliability: "режим и оборудование",
  data: "пригодность источников"
};

const VERDICTS: Record<string, string> = {
  ACCEPT: "принять план",
  REVISE: "пересмотреть план",
  REJECT: "отклонить план"
};

const RISK: Record<string, string> = {
  low: "низкий",
  medium: "средний",
  high: "высокий"
};

function toneOf(verdict: string): Lamp {
  if (verdict === "ACCEPT") return "pass";
  if (verdict === "REJECT") return "fail";
  return "unknown";
}

function ConfidenceBar({ value }: { value: number }) {
  const cells = Array.from({ length: 5 }, (_, index) => index < Math.round(value * 5));
  return (
    <span className="opinion__conf" aria-hidden="true">
      {cells.map((on, index) => (
        <span key={index} className={`opinion__conf-cell${on ? " opinion__conf-cell--on" : ""}`} />
      ))}
    </span>
  );
}

function Opinion({ opinion }: { opinion: AgentOpinion }) {
  const tone = toneOf(opinion.verdict);
  const risk = opinion.risk_level;
  const confidence = opinion.confidence;

  return (
    <article className={`opinion opinion--${tone}`}>
      <header className="opinion__head">
        <h4 className="opinion__role">
          <LampDot state={tone} />
          {ROLES[opinion.role] ?? opinion.role}
        </h4>
        <p className="opinion__scope">{SCOPES[opinion.role] ?? "зона ответственности не названа"}</p>
        <Tag tone={tone}>{VERDICTS[opinion.verdict] ?? opinion.verdict}</Tag>
      </header>

      <dl className="opinion__meta">
        <div className="opinion__metric">
          <dt>Уровень риска</dt>
          <dd>{risk === null || risk === undefined ? "не передан" : RISK[risk] ?? risk}</dd>
        </div>
        <div className="opinion__metric">
          <dt>Уверенность</dt>
          <dd>
            {confidence === null ? (
              "не передана"
            ) : (
              <>
                <ConfidenceBar value={confidence} />
                <span className="opinion__conf-value">{num(confidence, 2)}</span>
              </>
            )}
          </dd>
        </div>
      </dl>

      <div className="opinion__reasoning">
        <h5 className="opinion__label">Чем обосновано</h5>
        {opinion.reasons.length > 0 ? (
          <ul className="opinion__reasons">
            {opinion.reasons.map((reason) => (
              <li key={reason.code} className="opinion__reason">
                <p className="opinion__text">{reason.text}</p>
                <p className="opinion__code">
                  <code>{reason.code}</code>
                  {reason.candidate_id ? <> · план <code>{reason.candidate_id}</code></> : null}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Обоснование не передавалось.</Empty>
        )}
      </div>

      {opinion.proposed_constraints && opinion.proposed_constraints.length > 0 ? (
        <p className="opinion__proposal">
          Агент сам предложил ограничение:{" "}
          {opinion.proposed_constraints.map((item) => (
            <span key={`${item.type}-${item.limit}`} className="opinion__constraint">
              {constraintTypeText(item.type)}
              {item.limit ? ` (${limitText(item.limit)})` : ""}
              {typeof item.value === "number" ? ` ≥ ${num(item.value, 3)}` : ""}{" "}
              <code title="исходный код">{item.type}{item.limit ? `/${item.limit}` : ""}</code>
            </span>
          ))}
        </p>
      ) : null}

      <div className="opinion__foot">
        <JsonPanel title={`JSON мнения «${opinion.role}»`} value={opinion} openTo={2} />
      </div>
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
