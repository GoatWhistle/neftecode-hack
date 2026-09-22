import type { RunState } from "../../run/types";
import type { ScreenPayload } from "../../types";
import { num } from "../../format";
import "../../styles/agent-time.css";

const STATUS: Record<string, string> = { hold: "сохранить режим", recommend_scenario: "сценарная рекомендация", refuse: "отказ" };

const TERMINAL: Record<string, string> = {
  completed: "агентный этап завершён штатно",
  refused: "агенты отклонили допустимые планы — решение не выдано",
  skipped_data_refusal: "агентный этап не запускался: отказ по данным",
  budget_timeout: "агентный этап остановлен общим дедлайном",
  call_budget_exhausted: "исчерпан лимит вызовов модели",
  provider_error: "ошибка провайдера модели",
  not_configured: "провайдер модели не настроен",
  agent_failure: "сбой агентного этапа"
};

export interface AgentTerminal {
  kind: string; outcome: string | null; reason: string | null; status: string | null;
  domain_impossibility_proven: boolean; usage_complete: boolean; note: string;
}

/** Предварительный результат ядра, пока идёт агентная проверка. Не итог и не закрепляется. */
export function CorePreview({ run }: { run: RunState }) {
  if (run.status !== "running" || !run.core) return null;
  const core = run.core;
  return (
    <section className="agt agt--preliminary" role="status" aria-label="Предварительный результат ядра">
      <p className="agt__head"><b>Предварительно (ядро):</b> {STATUS[core.status ?? ""] ?? core.status ?? "нет статуса"}
        {core.plan_id ? <> · план <code>{core.plan_id}</code></> : null} · готово за {num(core.core_s, 1)} с</p>
      <p className="agt__note">
        Агентная проверка идёт{core.deadline_s ? ` (общий дедлайн ${num(core.deadline_s, 0)} с` : ""}
        {core.max_llm_calls ? `, не более ${core.max_llm_calls} вызовов)` : core.deadline_s ? ")" : ""}.
        {" "}{core.note}
      </p>
    </section>
  );
}

/** Итог агентного этапа: вид завершения, время ядра/агентов/всего, полнота расхода. */
export function AgentOutcome({ payload }: { payload: ScreenPayload }) {
  const agentic = payload.decision.agentic as (typeof payload.decision.agentic & {
    terminal?: AgentTerminal; timing?: { core_s?: number; agents_s?: number; total_s?: number };
  }) | null;
  if (!agentic?.terminal) return null;
  const { terminal, timing, budget } = agentic;
  const stopped = !["completed", "refused", "skipped_data_refusal"].includes(terminal.kind);
  return (
    <section className={`agt ${stopped ? "agt--stopped" : ""}`} aria-label="Итог агентного этапа">
      <p className="agt__head"><b>Агенты:</b> {TERMINAL[terminal.kind] ?? terminal.kind}</p>
      {agentic.provider === "scripted" || agentic.deterministic_policy ? <p className="agt__note">
        Сценарная политика инструментов; настоящая LLM в этом запуске не используется.
      </p> : null}
      <details><summary>Время и обращения</summary>
      <p className="agt__note">
        Время: ядро {timing?.core_s !== undefined ? `${num(timing.core_s, 1)} с` : "неизвестно"}
        {" · "}агенты {timing?.agents_s !== undefined ? `${num(timing.agents_s, 1)} с` : "неизвестно"}
        {" · "}всего {timing?.total_s !== undefined ? `${num(timing.total_s, 1)} с` : "неизвестно"}
        {budget?.llm_calls !== undefined ? ` · вызовов ${budget.llm_calls} из ${budget.max_llm_calls ?? "?"}` : ""}
        {terminal.usage_complete ? "" : " · расход неполный: часть вызовов не вернула usage (не ноль)"}
      </p>
      {terminal.reason ? <p className="agt__note">Причина в протоколе: <code>{terminal.reason}</code></p> : null}
      </details>
      {stopped ? (
        <p className="agt__note">
          {terminal.note}{terminal.domain_impossibility_proven ? " Отказ подтверждён расчётом проверок." : ""}
        </p>
      ) : null}
    </section>
  );
}
