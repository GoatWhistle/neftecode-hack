import type { BreakAct, OrchestratorAct } from "../run/agentActs";
import { callMeter, fallbackText } from "../run/agentMeters";
import { resolutionText } from "../run/agentVocab";
import { AGENT_NAMES, KIND_TEXT } from "../run/agentEvents";

export function GuardPlate({ act }: { act: BreakAct }) {
  const event = act.event;
  const passed = event.decision === "pass";
  const plans = event.candidate_ids ?? [];
  const named = plans.length > 0 ? `план ${plans.join(", ")}` : "выбранный план";
  return (
    <aside className={`plate plate--${passed ? "pass" : "fail"}`}>
      <p className="plate__line">
        Перепроверка кодом: {named} {passed ? "прошёл повторный Gate" : "повторный Gate не прошёл"}
      </p>
      <p className="plate__note">агенты к этой проверке отношения не имеют</p>
      {!passed && event.reason_codes && event.reason_codes.length > 0 ? (
        <p className="plate__codes">коды: {event.reason_codes.join(", ")}</p>
      ) : null}
    </aside>
  );
}

export function FallbackPlate({ act }: { act: BreakAct }) {
  const event = act.event;
  return (
    <aside className="plate plate--fallback">
      <p className="plate__line">{fallbackText(event.decision)}</p>
      {event.tool_result_summary ? (
        <p className="plate__detail">
          <code>{event.tool_result_summary}</code>
        </p>
      ) : null}
      {event.reason_codes && event.reason_codes.length > 0 ? (
        <p className="plate__codes">коды: {event.reason_codes.join(", ")}</p>
      ) : null}
      <p className="plate__note">дальше решение принимает детерминированный код</p>
    </aside>
  );
}

export function OverridePlate({ act }: { act: BreakAct }) {
  const ids = act.event.candidate_ids ?? [];
  const named = ids[0] ?? null;
  const chosen = ids[1] ?? null;
  return (
    <aside className="plate plate--override">
      <p className="plate__line">
        {named !== null && chosen !== null
          ? `Оркестратор назвал план ${named} → детерминированное ранжирование выбрало план ${chosen}`
          : "Выбор оркестратора переписан детерминированным ранжированием; пара планов не передана"}
      </p>
      <p className="plate__note">
        модель здесь не главная: её выбор перепроверяется кодом и может быть заменён
      </p>
      {act.event.reason_codes && act.event.reason_codes.length > 0 ? (
        <p className="plate__codes">коды: {act.event.reason_codes.join(", ")}</p>
      ) : null}
    </aside>
  );
}

export function ChoiceAgreement({ overridden }: { overridden: boolean | undefined }) {
  if (overridden === undefined) {
    return (
      <p className="agree agree--absent">
        Сервер не сообщил, сверялся ли выбор оркестратора с детерминированным ранжированием.
      </p>
    );
  }
  if (overridden) return null;
  return (
    <p className="agree">
      Выбор оркестратора совпал с детерминированным ранжированием: переписывать было нечего.
    </p>
  );
}

const FINAL_TEXT: Record<string, string> = {
  accepted: "ответ принят по схеме",
  accepted_from_text: "ответ принят из текста, схему агент не вызвал",
  invalid_final: "ответ не прошёл контракт",
  no_known_candidates: "агент назвал планы, которых нет среди рассмотренных"
};

export function ActRow({ act, deterministic }: { act: OrchestratorAct; deterministic: boolean }) {
  return (
    <section className={`act act--${act.agent}`}>
      <h4 className="act__title">{AGENT_NAMES[act.agent] ?? act.agent} работает</h4>
      <ol className="act__events">
        {act.events.map((event) => {
          const meter = event.kind === "llm_call" ? callMeter(event, deterministic) : null;
          const unmeasured = meter !== null && !meter.measured;
          return (
            <li key={event.seq} className={`act__event${unmeasured ? " act__event--unmeasured" : ""}`}>
              <span className="act__seq">{event.seq}</span>
              <div className="act__line">
                <p className="act__kind">{KIND_TEXT[event.kind] ?? event.kind}</p>
                {meter ? (
                  <p className="act__meter">
                    {[meter.latency, meter.usage, meter.finish].filter((part) => part !== "").join(" · ")}
                  </p>
                ) : null}
                {event.kind === "tool" ? (
                  <p className="act__meter">
                    {event.tool_name ?? resolutionText(event.decision)}
                    {event.decision === "error" ? " — вызов отклонён" : ""}
                  </p>
                ) : null}
                {event.kind === "resolution" ? (
                  <p className="act__meter">{resolutionText(event.decision)}</p>
                ) : null}
                {event.kind === "final" ? (
                  <p className="act__meter">{FINAL_TEXT[event.decision ?? ""] ?? event.decision ?? "без пометки"}</p>
                ) : null}
                {event.reason_codes && event.reason_codes.length > 0 ? (
                  <p className="act__codes">коды причин: {event.reason_codes.join(", ")}</p>
                ) : null}
                {event.kind !== "llm_call" && event.tool_result_summary ? (
                  <p className="act__detail">
                    <code>{event.tool_result_summary}</code>
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
