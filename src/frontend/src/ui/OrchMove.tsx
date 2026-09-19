import type { AgentEvent, StageFacts } from "../run/types";
import type { ProviderBand } from "../run/agentMeters";
import type { OrchestratorAct } from "../run/agentActs";
import { chronicle } from "../run/orchSteps";
import { callMeter } from "../run/agentMeters";
import { resolutionText } from "../run/agentVocab";
import { AGENT_NAMES } from "../run/agentEvents";
import { OrchTool } from "./OrchTool";

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
}

function callOrigin(event: AgentEvent, band: ProviderBand | null): string | null {
  const provider = event.provider ?? null;
  const model = event.model ?? null;
  if (provider === null && model === null) return null;
  if (band !== null && provider === band.provider && model === band.model) return null;
  return `${provider ?? "провайдер не передан"} · ${model ?? "модель не передана"}`;
}

export function OrchMoves({ act, deterministic, facts, band }: OrchMovesProps) {
  const log = chronicle(act, facts);
  const name = AGENT_NAMES[log.agent] ?? log.agent;

  return (
    <section className={`orch orch--${log.agent}`}>
      <h4 className="orch__title">{name} работает циклом</h4>
      <ol className="orch__moves">
        {log.moves.map((move) => {
          const meter = move.call === null ? null : callMeter(move.call, deterministic);
          return (
            <li className="orch-move" key={move.key}>
              <p className="orch-move__step">
                {move.step === null
                  ? "вне нумерации ходов"
                  : log.limit === null
                    ? `ход ${move.step}, предел ходов не передан`
                    : `ход ${move.step} из ${log.limit}`}
              </p>
              <div className="orch-move__body">
                {meter !== null && move.call !== null ? (
                  <p className={`orch-move__call${meter.measured ? "" : " orch-move__call--unmeasured"}`}>
                    <span className="orch-move__seq">№{move.call.seq}</span>
                    обращение к модели
                    <span className="orch-move__meter">
                      {[meter.latency, meter.usage, meter.finish]
                        .filter((part) => part !== "")
                        .join(" · ")}
                    </span>
                    {callOrigin(move.call, band) !== null ? (
                      <span className="orch-move__origin">{callOrigin(move.call, band)}</span>
                    ) : null}
                  </p>
                ) : null}

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
          );
        })}
      </ol>
    </section>
  );
}
