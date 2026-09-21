import type { AgentEvent } from "../run/types";
import { readOrchTool } from "../run/orchTool";
import { RawJson } from "./RawJson";

export function OrchTool({ event }: { event: AgentEvent }) {
  const read = readOrchTool(event);
  const ids = read.askedIds;
  return (
    <li className={`orch-tool${read.failed ? " orch-tool--failed" : ""}`}>
      <p className="orch-tool__head">
        <span className="orch-tool__seq">{event.seq < 10 ? `0${event.seq}` : event.seq}</span>
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

      {read.inputRaw !== null && read.inputRaw !== "{}"
        && (read.inputTruncated || (read.asked === null && read.question === null)) ? (
        <RawJson label="аргументы вызова" text={read.inputRaw} serverLimit={200} />
      ) : null}

      {read.resultRaw !== null && !read.failed ? (
        <RawJson label="ответ инструмента" text={read.resultRaw} full={read.resultFull} />
      ) : null}
    </li>
  );
}
