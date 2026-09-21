import type { Agentic } from "../types";
import { num } from "../format";
import { ROLE_TEXT } from "../run/agentMeters";
import { constraintTypeText, limitText } from "../run/orchRead";
import { Empty, Field, Fields, Note } from "./Primitives";
import { JsonPanel } from "./Json";

const ACTIONS: Record<string, string> = {
  select: "выбрать план",
  refuse: "отказаться от рекомендации",
  hold: "сохранить режим",
  keep_legacy: "оставить план детерминированного контура"
};

export function VetoMap({ vetoes }: { vetoes: Record<string, string[]> | undefined }) {
  if (vetoes === undefined) {
    return (
      <div className="veto">
        <h5 className="veto__title">Вето агентов</h5>
        <p className="veto__none">Карта вето сервером не передавалась.</p>
      </div>
    );
  }
  const entries = Object.entries(vetoes);
  return (
    <div className="veto">
      <h5 className="veto__title">Вето агентов</h5>
      {entries.length === 0 ? (
        <p className="veto__none">Вето ни на один план не накладывалось.</p>
      ) : (
        <ul className="veto__rows">
          {entries.map(([plan, roles]) => (
            <li key={plan} className="veto__row">
              <code className="veto__plan">{plan}</code>
              <span className="veto__arrow" aria-hidden="true">→</span>
              <span className="veto__roles">
                {roles.length === 0 ? (
                  <span className="veto__none">роли не названы</span>
                ) : (
                  roles.map((role) => (
                    <span key={role} className="veto__pill">{ROLE_TEXT[role] ?? role}</span>
                  ))
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AgentFinal({ agentic }: { agentic: Agentic | null }) {
  const final = agentic?.final ?? null;
  const budget = agentic?.budget ?? null;
  const constraints = agentic?.constraints_applied ?? [];

  return (
    <div className="agfinal">
      <h4 className="agents__heading">Чем закончился диалог</h4>
      {final ? (
        <>
          <p className="agfinal__summary">{final.summary}</p>
          <Fields>
            <Field label="Действие">{ACTIONS[final.action] ?? final.action}</Field>
            <Field label="План">{final.candidate_id ?? "план не выбран"}</Field>
            <Field label="Коды причин">
              {final.reason_codes.length > 0 ? final.reason_codes.join(", ") : "не передавались"}
            </Field>
          </Fields>
          {final.evidence_refs && final.evidence_refs.length > 0 ? (
            <p className="agfinal__evidence">
              На чём основано: {final.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}
            </p>
          ) : null}
        </>
      ) : (
        <Empty>Итог диалога оркестратора не передавался.</Empty>
      )}

      <VetoMap vetoes={agentic?.vetoed_candidates} />

      {constraints.length > 0 ? (
        <p className="agfinal__constraints">
          Ограничения, наложенные агентами по ходу поиска:{" "}
          {constraints.map((item) => (
            <span key={`${item.type}-${item.limit}`} className="opinion__constraint">
              {constraintTypeText(item.type)}
              {item.limit ? ` (${limitText(item.limit)})` : ""}
              {typeof item.value === "number" ? ` ≥ ${num(item.value, 3)}` : ""}{" "}
              <code title="исходный код">{item.type}{item.limit ? `/${item.limit}` : ""}</code>
            </span>
          ))}
        </p>
      ) : null}

      {budget ? (
        <Fields>
          <Field label="Вызовов модели">
            {num(budget.llm_calls, 0)} из {num(budget.max_llm_calls, 0)}
          </Field>
          <Field label="По ролям">
            {Object.entries(budget.llm_calls_by_role ?? {})
              .map(([role, count]) => `${ROLE_TEXT[role] ?? role}: ${count}`)
              .join(", ") || "не передавались"}
          </Field>
          <Field label="Токены">
            {budget.usage && (budget.usage["total_tokens"] ?? 0) > 0
              ? `${num(budget.usage["prompt_tokens"], 0)} на запрос, ${num(budget.usage["completion_tokens"], 0)} на ответ, всего ${num(budget.usage["total_tokens"], 0)}`
              : "ноль: живая модель не вызывалась"}
          </Field>
          <Field label="Повторных поисков">{num(budget.replans, 0)}</Field>
          <Field label="Консультаций специалистов">
            {Object.entries(budget.consults ?? {})
              .map(([role, count]) => `${ROLE_TEXT[role] ?? role}: ${count}`)
              .join(", ") || "не передавались"}
          </Field>
        </Fields>
      ) : (
        <Note>Счётчики вызовов не передавались.</Note>
      )}

      <JsonPanel title="JSON: итог и бюджет агентного слоя" value={{ final, budget, constraints, vetoed_candidates: agentic?.vetoed_candidates,
        llm_choice_overridden: agentic?.llm_choice_overridden }} openTo={1} />
    </div>
  );
}
