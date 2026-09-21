import type { AgentEvent, StageFacts } from "../run/types";
import type { ProviderBand } from "../run/agentMeters";
import type { OrchestratorAct } from "../run/agentActs";
import type { OrchMove } from "../run/orchSteps";
import { chronicle } from "../run/orchSteps";
import { callMeter } from "../run/agentMeters";
import { resolutionText } from "../run/agentVocab";
import { AGENT_NAMES } from "../run/agentEvents";
import { OrchTool } from "./OrchTool";

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

const FINAL_TEXT: Record<string, string> = {
  accepted: "ответ принят по схеме",
  accepted_from_text: "ответ принят из текста, схему агент не вызвал",
  invalid_final: "ответ не прошёл контракт",
  no_known_candidates: "агент назвал планы, которых нет среди рассмотренных"
};

function Decision({ event, text }: { event: AgentEvent; text: string }) {
  return (
    <div className="orch-decision">
      <p className="orch-decision__label">
        решение
        {event.tool_name ? <span className="orch-decision__tool">{event.tool_name}</span> : null}
      </p>
      <p className="orch-decision__text">{text}</p>
      {event.reason_codes && event.reason_codes.length > 0 ? (
        <p className="orch-decision__codes">коды причин: {event.reason_codes.join(", ")}</p>
      ) : null}
      {event.candidate_ids && event.candidate_ids.length > 0 ? (
        <p className="orch-decision__ids">планы: {event.candidate_ids.join(", ")}</p>
      ) : null}
      {event.tool_result_summary ? (
        <p className="orch-decision__detail">
          <code>{event.tool_result_summary}</code>
        </p>
      ) : null}
    </div>
  );
}

export interface OrchMovesProps {
  act: OrchestratorAct;
  deterministic: boolean;
  facts: StageFacts | undefined;
  band: ProviderBand | null;
  offset: number;
}

function MoveCall({ move, deterministic, band }: { move: OrchMove; deterministic: boolean;
  band: ProviderBand | null }) {
  const call = move.call;
  if (call === null) return null;
  const meter = callMeter(call, deterministic);
  const origin = callOrigin(call, band);
  const parts = [meter.latency, meter.usage, meter.finish].filter((part) => part !== "");
  return (
    <p className={`orch-move__call${meter.measured ? "" : " orch-move__call--unmeasured"}`}>
      <span className="orch-move__seq">{pad(call.seq)}</span>
      {meter.measured ? (
        <>
          обращение к модели
          <span className="orch-move__meter">{parts.join(" · ")}</span>
        </>
      ) : (
        <span className="orch-move__meter">
          {deterministic ? "ход рассчитан политикой, модель не вызывалась" : parts.join(" · ")}
        </span>
      )}
      {origin !== null ? <span className="orch-move__origin">{origin}</span> : null}
    </p>
  );
}

function callOrigin(event: AgentEvent, band: ProviderBand | null): string | null {
  const provider = event.provider ?? null;
  const model = event.model ?? null;
  if (provider === null && model === null) return null;
  if (band !== null && provider === band.provider && model === band.model) return null;
  return `${provider ?? "провайдер не передан"} · ${model ?? "модель не передана"}`;
}

export function OrchMoves({ act, deterministic, facts, band, offset }: OrchMovesProps) {
  const log = chronicle(act, facts, offset);
  const name = AGENT_NAMES[log.agent] ?? log.agent;
  const span = log.limit === null
    ? "предел шагов сервер не передал"
    : `предел ${log.limit} шагов на отрезок`;
  const from = log.firstStep ?? 1;
  const range = log.total <= 1 ? `ход ${pad(from)}` : `ходы ${pad(from)}–${pad(from + log.total - 1)}`;
  const head = `${log.resumed ? "цикл продолжен" : "цикл рассуждения"}, ${range} · ${span}`;

  return (
    <section className={`orch orch--${log.agent}${log.resumed ? " orch--resumed" : ""}`}
      aria-label={`${name}: ${head}`}>
      <h5 className="orch__title">{head}</h5>
      <ol className="orch__moves">
        {log.moves.map((move) => (
          <li key={move.key}
            className={`orch-move${move.bare ? " orch-move--bare" : ""}${
              move.lone ? " orch-move--lone" : ""}`}>
            <p className="orch-move__step">
              <b>{pad(move.order)}</b>
              ход
              {move.step === null ? (
                <span className="orch-move__raw">номера шага сервер не передал</span>
              ) : (
                <span className="orch-move__raw">шаг {pad(move.step)} в трассе</span>
              )}
            </p>
            <div className="orch-move__body">
              <MoveCall move={move} deterministic={deterministic} band={band} />

              {move.tools.length > 0 ? (
                <ol className="orch-move__tools">
                  {move.tools.map((tool) => <OrchTool key={tool.seq} event={tool} />)}
                </ol>
              ) : null}

              {move.resolutions.map((event) => (
                <Decision key={event.seq} event={event} text={resolutionText(event.decision)} />
              ))}
              {move.finals.map((event) => (
                <Decision key={event.seq} event={event}
                  text={FINAL_TEXT[event.decision ?? ""] ?? event.decision ?? "итог без пометки"} />
              ))}
              {move.others.map((event) => (
                <p className="orch-move__other" key={event.seq}>
                  событие {event.kind}
                  {event.decision ? `: ${event.decision}` : ", без пометки решения"}
                </p>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
