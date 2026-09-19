import type { AgentEvent } from "../run/types";
import { readOrchTool } from "../run/orchTool";

function Raw({ label, text, truncated }: { label: string; text: string; truncated: boolean }) {
  return (
    <div className="orch-raw">
      <p className="orch-raw__note">
        {truncated
          ? `${label}: сводка обрезана сервером, разобрать не удалось — показан текст как есть`
          : `${label}: разобрать не удалось — показан текст как есть`}
      </p>
      <p className="orch-raw__text">
        <code>{text}</code>
      </p>
    </div>
  );
}

export function OrchTool({ event }: { event: AgentEvent }) {
  const read = readOrchTool(event);
  const ids = read.askedIds;
  return (
    <li className={`orch-tool${read.failed ? " orch-tool--failed" : ""}`}>
      <p className="orch-tool__head">
        <span className="orch-tool__seq">№{event.seq}</span>
        <span className="orch-tool__verb">{read.title}</span>
        {read.asked !== null ? <span className="orch-tool__arg">{read.asked}</span> : null}
        <span className="orch-tool__name">{read.tool}</span>
      </p>

      {read.question !== null ? (
        <p className="orch-tool__question">
          <span className="orch-tool__quote">вопрос агента:</span> {read.question}
        </p>
      ) : null}

      {read.failed ? (
        <p className="orch-tool__error">
          вызов отклонён{read.error !== null ? `: ${read.error}` : ", причина не передана"}
        </p>
      ) : null}

      {read.facts.length > 0 && read.resultPartial ? (
        <p className="orch-tool__partial">
          сводка обрезана сервером: ниже только те величины, что пришли целиком
        </p>
      ) : null}

      {read.facts.length > 0 ? (
        <dl className="orch-facts">
          {read.facts.map((fact) => (
            <div className="orch-facts__row" key={fact.label}>
              <dt className="orch-facts__label">{fact.label}</dt>
              <dd className="orch-facts__value">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {read.rank !== null ? (
        <div className="orch-rank">
          <p className="orch-rank__label">правило сортировки, по порядку</p>
          <ol className="orch-rank__keys">
            {read.rank.keys.length === 0 ? (
              <li className="orch-rank__key orch-rank__key--absent">ключи сортировки не переданы</li>
            ) : (
              read.rank.keys.map((key, index) => (
                <li className="orch-rank__key" key={`${key}-${index}`}>{key}</li>
              ))
            )}
          </ol>
          {read.rank.reason !== null ? <p className="orch-rank__reason">{read.rank.reason}</p> : null}
        </div>
      ) : null}

      {ids.length > 0 && read.asked === null ? (
        <p className="orch-tool__ids">планы в ответе: {ids.join(", ")}</p>
      ) : null}

      {event.reason_codes && event.reason_codes.length > 0 ? (
        <p className="orch-tool__codes">коды причин: {event.reason_codes.join(", ")}</p>
      ) : null}

      {read.inputRaw !== null && read.asked === null && read.question === null
        && !read.inputTruncated && read.inputRaw !== "{}" ? (
        <Raw label="аргументы" text={read.inputRaw} truncated={false} />
      ) : null}
      {read.inputTruncated ? <Raw label="аргументы" text={read.inputRaw ?? ""} truncated /> : null}

      {read.resultRaw !== null && !read.resultParsed && !read.failed
        && (read.facts.length === 0 || read.resultPartial) ? (
        <Raw label="ответ инструмента" text={read.resultRaw} truncated={read.resultTruncated} />
      ) : null}
    </li>
  );
}
