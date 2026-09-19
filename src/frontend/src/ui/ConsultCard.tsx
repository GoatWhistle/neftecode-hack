import type { ConsultAct, ToolStep } from "../run/agentActs";
import { constraintPicks, toolSteps } from "../run/agentActs";
import type { AgentEvent, StageFacts } from "../run/types";
import { callMeter } from "../run/agentMeters";
import { AGENT_NAMES } from "../run/agentEvents";
import { ConstraintVocabulary } from "./AgentMeters";

const VERDICT_TEXT: Record<string, string> = {
  ACCEPT: "план разумен",
  REVISE: "допустим, но стоит ужесточить поиск",
  REJECT: "не прошёл",
  UNKNOWN: "данных не хватило"
};

const RISK_TEXT: Record<string, string> = {
  low: "риск низкий",
  medium: "риск средний",
  high: "риск высокий"
};

function StepRow({ step, deterministic }: { step: ToolStep; deterministic: boolean }) {
  return (
    <ul className="consult__tools">
      {step.llmCalls.map((call) => {
        const meter = callMeter(call, deterministic);
        return (
          <li key={`llm-${call.seq}`}
            className={`consult__tool consult__tool--call${meter.measured ? "" : " consult__tool--unmeasured"}`}>
            <span className="consult__tool-name">обращение к модели</span>
            <span className="consult__tool-state">
              {[meter.latency, meter.usage, meter.finish].filter((part) => part !== "").join(" · ")}
            </span>
          </li>
        );
      })}
      {step.tools.map((tool) => {
        const failed = tool.decision === "error";
        const codes = tool.reason_codes ?? [];
        return (
          <li key={tool.seq} className={`consult__tool${failed ? " consult__tool--failed" : ""}`}>
            <span className="consult__tool-name">{tool.tool_name ?? "инструмент не назван"}</span>
            <span className="consult__tool-state">{failed ? "вызов отклонён" : "вернул результат"}</span>
            {failed && codes.length > 0 ? (
              <span className="consult__tool-why">причина: {codes.join(", ")}</span>
            ) : null}
            {failed && tool.tool_result_summary ? (
              <span className="consult__tool-why">{tool.tool_result_summary}</span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Steps({ act, limit, deterministic }: { act: ConsultAct; limit: number | null;
  deterministic: boolean }) {
  const steps = toolSteps(act);
  if (steps.length === 0) {
    return <p className="consult__none">ни одного шага специалист не сделал</p>;
  }
  return (
    <div className="consult__steps">
      <p className="consult__steps-head">
        итераций специалиста: {limit === null ? steps.length : `${steps.length} из ${limit}`}
      </p>
      {steps.map((step, index) => (
        <section key={step.step} className="consult__step">
          <h6 className="consult__step-title">шаг {index + 1}</h6>
          <StepRow step={step} deterministic={deterministic} />
        </section>
      ))}
    </div>
  );
}

function Confidence({ act }: { act: ConsultAct }) {
  const opinion = act.opinion;
  if (!opinion || !opinion.confidenceSent || opinion.confidence === null) {
    return <p className="consult__confidence consult__confidence--absent">уверенность не передана</p>;
  }
  const steps = Math.round(Math.min(1, Math.max(0, opinion.confidence)) * 10);
  return (
    <p className="consult__confidence">
      <span className="consult__conf-bar" aria-hidden="true">
        {Array.from({ length: 10 }, (_, index) => (
          <span key={index} className={`consult__conf-cell${index < steps ? " consult__conf-cell--on" : ""}`} />
        ))}
      </span>
      <span className="consult__conf-text">уверенность {steps} из 10, как передал агент</span>
    </p>
  );
}

export interface ConsultCardProps {
  act: ConsultAct;
  deterministic: boolean;
  closed: boolean;
  facts: StageFacts | undefined;
  breakEvent: AgentEvent | null;
}

function breakReason(event: AgentEvent | null): string | null {
  if (event === null) return null;
  const summary = event.tool_result_summary;
  if (summary) return summary;
  if (event.reason_codes && event.reason_codes.length > 0) return event.reason_codes.join(", ");
  return event.decision ?? null;
}

export function ConsultCard({ act, deterministic, closed, facts, breakEvent }: ConsultCardProps) {
  const opinion = act.opinion;
  const verdict = opinion?.verdict ?? null;
  const broken = act.resolution === null && breakEvent !== null;
  const state = act.resolution === null
    ? (broken ? "оборвана откатом" : closed ? "оборвана" : "идёт")
    : "завершена";
  const why = broken ? breakReason(breakEvent) : null;
  const limit = facts?.budget_limits?.["specialist_max_calls"] ?? null;
  const picks = constraintPicks(opinion?.constraints ?? []);
  const note = opinion?.truncated
    ? "сводка мнения обрезана сервером до 300 символов, разобрать предложенные ограничения не удалось"
    : null;

  return (
    <article className={`consult consult--${act.role}`}>
      <header className="consult__head">
        <span className="consult__index">консультация {act.index}</span>
        <h4 className="consult__title">
          Оркестратор → {AGENT_NAMES[act.role] ?? act.role}
          {act.candidateIds.length > 0 ? `, планы ${act.candidateIds.join(", ")}` : ", планы не названы"}
        </h4>
        <span className="consult__state">{state}</span>
      </header>

      <div className="consult__body">
        <section className="consult__part">
          <h5 className="consult__label">о чём спросил</h5>
          {act.focus !== null ? (
            <p className="consult__focus">{act.focus}</p>
          ) : act.candidateIds.length > 0 ? (
            <p className="consult__focus">
              фокус запроса не передан; спросили про планы {act.candidateIds.join(", ")}
            </p>
          ) : (
            <p className="consult__none">ни фокуса, ни списка планов в запросе не передавалось</p>
          )}
        </section>

        <section className="consult__part">
          <h5 className="consult__label">что делал специалист</h5>
          <Steps act={act} limit={typeof limit === "number" ? limit : null}
            deterministic={deterministic} />
        </section>

        <section className="consult__part">
          <h5 className="consult__label">вердикт</h5>
          {verdict === null ? (
            <p className="consult__none">
              {act.resolution === null ? "вердикт ещё не оформлен" : "вердикт не передан"}
            </p>
          ) : (
            <p className={`consult__verdict consult__verdict--${verdict.toLowerCase()}`}>
              <b className="consult__verdict-code">{verdict}</b>
              <span className="consult__verdict-text">{VERDICT_TEXT[verdict] ?? "смысл вердикта не описан"}</span>
              {opinion?.riskLevel ? (
                <span className="consult__risk">{RISK_TEXT[opinion.riskLevel] ?? opinion.riskLevel}</span>
              ) : null}
            </p>
          )}
          <Confidence act={act} />
          {act.vetoed.length > 0 ? (
            <p className="consult__veto">вето наложено на планы: {act.vetoed.join(", ")}</p>
          ) : null}
          {act.reasonCodes.length > 0 ? (
            <p className="consult__codes">коды причин: {act.reasonCodes.join(", ")}</p>
          ) : null}
          {broken ? (
            <p className="consult__broken">
              консультацию оборвал откат
              {why !== null ? <>: <code>{why}</code></> : "; причину сервер не передал"}
            </p>
          ) : null}
        </section>

        <ConstraintVocabulary picks={picks} note={note} />
      </div>
    </article>
  );
}
