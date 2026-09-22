import type { ConsultAct, ToolStep } from "../run/agentActs";
import { constraintPicks, toolSteps } from "../run/agentActs";
import type { AgentEvent, StageFacts } from "../run/types";
import { callMeter } from "../run/agentMeters";
import { readSpecialistTool } from "../run/orchTool";
import { reasonCodesText } from "../run/agentVocab";
import { AGENT_NAMES } from "../run/agentEvents";
import { ConstraintVocabulary } from "./AgentMeters";
import { RawJson } from "./RawJson";

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
        const read = readSpecialistTool(tool);
        return (
          <li key={tool.seq} className={`consult__tool${failed ? " consult__tool--failed" : ""}`}>
            <span className="consult__tool-name">{read.title}</span>
            <span className="consult__tool-code">{tool.tool_name ?? "инструмент не назван"}</span>
            {failed ? (
              <span className="consult__tool-state">вызов отклонён</span>
            ) : null}
            {failed && codes.length > 0 ? (
              <span className="consult__tool-why">причина: {reasonCodesText(codes)}</span>
            ) : null}
            {failed && tool.tool_result_summary ? (
              <span className="consult__tool-why">{tool.tool_result_summary}</span>
            ) : null}
            {!failed && read.facts.length > 0 ? (
              <dl className="consult__tool-facts">
                {read.facts.map((fact) => (
                  <div className="consult__tool-fact" key={fact.label}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {!failed && read.facts.length === 0 ? (
              <span className="consult__tool-state">вернул результат</span>
            ) : null}
            {!failed && read.resultRaw !== null ? (
              <RawJson label="ответ инструмента" text={read.resultRaw} full={read.resultFull} />
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
      <ol className="consult__step-list">
        {steps.map((step, index) => (
          <li key={step.step} className="consult__step">
            <span className="consult__step-title">
              {index < 9 ? `0${index + 1}` : index + 1}
            </span>
            <StepRow step={step} deterministic={deterministic} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function confidenceLevel(value: number): string {
  if (value >= 0.7) return "высокая";
  if (value >= 0.4) return "средняя";
  return "низкая";
}

function Confidence({ act }: { act: ConsultAct }) {
  const opinion = act.opinion;
  if (!opinion || !opinion.confidenceSent || opinion.confidence === null) {
    return <p className="consult__confidence consult__confidence--absent">уверенность не передана</p>;
  }
  return (
    <p className="consult__confidence" title={`${opinion.confidence.toFixed(2)} — самооценка модели, не калибрована по исходам`}>
      <span className="consult__conf-text">
        {confidenceLevel(opinion.confidence)} самооценка модели (не калибрована)
      </span>
    </p>
  );
}

function Reasons({ act }: { act: ConsultAct }) {
  const reasons = act.opinion?.reasons ?? [];
  if (reasons.length === 0) return null;
  return (
    <ul className="consult__reasons">
      {reasons.map((reason, index) => (
        <li className="consult__reason" key={`${reason.code}-${index}`}>
          {reason.text !== "" ? <span className="consult__reason-text">{reason.text}</span> : null}
          <span className="consult__reason-meta">
            {reason.code !== "" ? <code>{reason.code}</code> : null}
            {reason.candidateId !== null ? (
              <span className="consult__reason-plan">план {reason.candidateId}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function PerPlan({ act }: { act: ConsultAct }) {
  const verdicts = Object.entries(act.opinion?.candidateVerdicts ?? {});
  const preferred = act.opinion?.preferred ?? [];
  if (verdicts.length === 0 && preferred.length === 0) return null;
  return (
    <div className="consult__perplan">
      {verdicts.length > 0 ? (
        <ul className="consult__plan-list">
          {verdicts.map(([plan, value]) => (
            <li className={`consult__plan-row consult__plan-row--${value.toLowerCase()}`} key={plan}>
              <span className="consult__plan-id">{plan}</span>
              <span className="consult__plan-verdict">{value}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {preferred.length > 0 ? (
        <p className="consult__preferred">агент предпочёл: {preferred.join(", ")}</p>
      ) : null}
    </div>
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
  if (event.reason_codes && event.reason_codes.length > 0) return reasonCodesText(event.reason_codes);
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
    ? "сводка мнения обрезана сервером и полной версии нет: предложенные ограничения разобрать не удалось"
    : opinion?.fromFull
      ? "сводка мнения обрезана сервером — разобрана полная версия ответа"
      : null;

  return (
    <article className={`consult consult--${act.role}`}>
      <header className="consult__head">
        <span className="consult__index">консультация</span>
        <h4 className="consult__title">
          Оркестратор → <b>{AGENT_NAMES[act.role] ?? act.role}</b>
          <span className="consult__plans">
            {act.candidateIds.length > 0 ? act.candidateIds.join(", ") : "планы не названы"}
          </span>
        </h4>
        <span className={`consult__state${state === "идёт" ? " consult__state--live" : ""}`}>
          {state}
        </span>
        <p className="consult__ask">
          <span className="consult__ask-label">о чём спросил</span>
          {act.focus !== null ? (
            <span className="consult__focus">{act.focus}</span>
          ) : act.candidateIds.length > 0 ? (
            <span className="consult__focus">
              фокус запроса не передан; спросили про планы {act.candidateIds.join(", ")}
            </span>
          ) : (
            <span className="consult__none">ни фокуса, ни списка планов в запросе не передавалось</span>
          )}
        </p>
      </header>

      <div className="consult__body">
        <section className="consult__part">
          <h5 className="consult__label">что делал специалист</h5>
          <Steps act={act} limit={typeof limit === "number" ? limit : null}
            deterministic={deterministic} />
        </section>

        <section className="consult__part consult__part--verdict">
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
          <Reasons act={act} />
          <PerPlan act={act} />
          {act.vetoed.length > 0 ? (
            <p className="consult__veto">вето наложено на планы: {act.vetoed.join(", ")}</p>
          ) : null}
          {act.reasonCodes.length > 0 ? (
            <p className="consult__codes">коды причин: {reasonCodesText(act.reasonCodes)}</p>
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
