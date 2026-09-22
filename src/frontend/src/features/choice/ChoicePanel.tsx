import { useState } from "react";
import type { ChoiceCard, ChoiceReason, ScreenPayload } from "../../types";
import { Empty } from "../../ui/Primitives";
import { num } from "../../format";
import { agentStopNote, CATEGORY_TEXT, columnsOf, reasonKey, STAGE_TEXT, VERDICT_TEXT } from "./model";
import "../../styles/choice.css";

export interface ChoicePanelProps {
  payload: ScreenPayload;
  /** Открывает существующий what-if; сам по себе ничего не пересчитывает. */
  onChangeCondition?: () => void;
}

function value(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined ? "нет числа" : num(v, digits);
}

function Evidence({ reason, decisionId }: { reason: ChoiceReason; decisionId: string | null }) {
  const refs = reason.evidence ?? [];
  return (
    <div className="chc__evidence">
      {refs.length > 0 ? (
        <table className="chc__table">
          <caption>
            Проверки этого запуска{decisionId ? <> · запись <code>{decisionId}</code></> : null}
            {reason.evidence_total !== undefined && reason.evidence_total > refs.length
              ? ` · показаны ${refs.length} из ${reason.evidence_total}` : null}
          </caption>
          <thead>
            <tr>
              <th scope="col">Ограничение</th>
              <th scope="col">Момент</th>
              <th scope="col">Значение</th>
              <th scope="col">Предел</th>
              <th scope="col">Статус</th>
            </tr>
          </thead>
          <tbody>
            {refs.map((ref, i) => (
              <tr key={`${ref.constraint_id}-${ref.status}-${i}`}>
                <th scope="row">
                  <code>{ref.constraint_id ?? "—"}</code>
                  {ref.points > 1 ? <span className="chc__muted"> · точек: {ref.points}</span> : null}
                </th>
                <td>{ref.time_hours === null ? "нет времени" : `${num(ref.time_hours, 1)} ч`}</td>
                <td>{value(ref.observed)}{ref.unit ? ` ${ref.unit}` : ""}</td>
                <td>
                  {value(ref.limit)}{ref.unit ? ` ${ref.unit}` : ""}
                  <span className="chc__muted"> ({ref.limit_source ?? "источник не передан"})</span>
                </td>
                <td className={`chc__status chc__status--${ref.status}`}>
                  {ref.status === "fail" ? "нарушение" : ref.status === "unknown" ? "UNKNOWN" : "пройдено"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {reason.rule ? (
        <p className="chc__rule">
          Правило <code>{reason.rule.id}</code>
          {reason.rule.value !== null ? <> · порог {String(reason.rule.value)}</> : null}
          {reason.rule.observed !== null && reason.rule.observed !== undefined
            ? <> · значение {typeof reason.rule.observed === "number" ? num(reason.rule.observed, 4) : String(reason.rule.observed)}</>
            : null}
          {" · источник "}<code>{reason.rule.source}</code>
        </p>
      ) : null}
      {reason.events && reason.events.length > 0 ? (
        <ul className="chc__events">{reason.events.map((e) => <li key={e}>{e}</li>)}</ul>
      ) : null}
      {refs.length === 0 && !reason.rule && !(reason.events?.length) ? (
        <p className="chc__muted">Числового доказательства у этой причины нет.</p>
      ) : null}
    </div>
  );
}

function Card({ card, title, decisionId, open, onToggle, vetoRoles }: {
  card: ChoiceCard; title: string; decisionId: string | null;
  open: Set<string>; onToggle: (key: string) => void; vetoRoles?: string[] | undefined;
}) {
  return (
    <article className={`chc__card chc__card--${card.verdict}`} aria-label={`${title}: ${card.candidate_id}`}>
      <header className="chc__head">
        <span className="chc__title">{title}</span>
        <code className="chc__id">{card.candidate_id}</code>
        <span className={`chc__verdict chc__verdict--${card.verdict}`}>{VERDICT_TEXT[card.verdict]}</span>
      </header>
      <dl className="chc__figures">
        <div><dt>Стоимостный прокси</dt><dd>{value(card.cost_per_tonne, 4)} у.е./т</dd></div>
        <div><dt>Выпуск</dt><dd>{value(card.production_t, 1)} т</dd></div>
        <div><dt>Изменений</dt><dd>{value(card.changes, 0)}</dd></div>
      </dl>
      {card.reasons.length > 0 ? (
        <ul className="chc__reasons">
          {card.reasons.map((reason, index) => {
            const key = reasonKey(card, reason, index);
            const expanded = open.has(key);
            return (
              <li key={key}>
                <button type="button" className="chc__reason" aria-expanded={expanded} onClick={() => onToggle(key)}>
                  <span className={`chc__cat chc__cat--${reason.category}`}>{CATEGORY_TEXT[reason.category] ?? reason.category}</span>
                  <span>{reason.text}</span>
                </button>
                {expanded ? <Evidence reason={reason} decisionId={decisionId} /> : null}
              </li>
            );
          })}
        </ul>
      ) : card.verdict === "selected" ? (
        <p className="chc__muted">Прошёл Gate и финальную перепроверку; проверки — в «Доказательствах».</p>
      ) : null}
      {vetoRoles && vetoRoles.length > 0 ? (
        <p className="chc__muted">
          Агент наложил вето ({vetoRoles.join(", ")}), но итог ядра агентным этапом не изменён.
        </p>
      ) : null}
      {card.reasons.length > 1 ? (
        <p className="chc__muted">Причин несколько: ни одна не выдаётся за единственную.</p>
      ) : null}
    </article>
  );
}

export function ChoicePanel({ payload, onChangeCondition }: ChoicePanelProps) {
  const decision = payload.decision;
  const hasField = Object.prototype.hasOwnProperty.call(decision, "choice");
  const choice = decision.choice;
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [showOthers, setShowOthers] = useState(false);
  const toggle = (key: string) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  if (!hasField || !choice) {
    return <Empty>Связь «вариант → проверка → решение» в этой записи не сохранена: запись сделана до её появления.</Empty>;
  }

  const columns = columnsOf(choice);
  const stop = agentStopNote(decision.agentic);
  const refused = choice.status === "refuse";
  const decisionId = choice.decision_id;
  const vetoes = choice.agents ? {} : (decision.agentic?.vetoed_candidates ?? {});
  const roles = (id: string) => vetoes[id];

  return (
    <section className="chc" aria-labelledby="chc-title">
      <h3 className="chc__rubric" id="chc-title">
        {refused ? "Почему решение не выдано" : "Почему этот вариант, а не дешевле"}
      </h3>

      {choice.determined_by.length > 0 ? (
        <ol className="chc__stages" aria-label="Что определило итог">
          {choice.determined_by.map((item, i) => (
            <li key={`${item.stage}-${i}`}>
              <b>{STAGE_TEXT[item.stage] ?? item.stage}:</b> {item.text}
              {item.candidate_ids.filter(Boolean).length > 0
                ? <> (<code>{item.candidate_ids.filter(Boolean).join(", ")}</code>)</> : null}
            </li>
          ))}
        </ol>
      ) : null}

      {refused && choice.refusal ? (
        <p className="chc__refusal">
          Стадия отказа: <b>{STAGE_TEXT[choice.refusal.stage] ?? choice.refusal.stage}</b>
          {choice.refusal.agents_skipped ? " · агентный этап не запускался: отказ по данным." : null}
          {choice.refusal.domain_impossibility_proven
            ? " · невозможность подтверждена расчётом проверок."
            : " · предметная невозможность расчётом не доказана."}
        </p>
      ) : null}

      {stop ? <p className="chc__warn">{stop}</p> : null}

      {!refused ? (
        <div className="chc__cols">
          {columns.hold ? (
            <Card card={columns.hold} title="Сохранить режим" decisionId={decisionId} open={open} onToggle={toggle}
              vetoRoles={roles(columns.hold.candidate_id)} />
          ) : choice.hold_id === choice.selected_id && choice.selected_id !== null ? null : (
            <div className="chc__card chc__card--none">
              <span className="chc__title">Сохранить режим</span>
              <p className="chc__muted">Текущий режим в этом запуске не рассчитывался — сравнивать не с чем.</p>
            </div>
          )}
          {columns.selected ? (
            <Card card={columns.selected}
              title={choice.selected_id === choice.hold_id ? "Выбран: сохранить режим" : "Выбранный"}
              decisionId={decisionId} open={open} onToggle={toggle} />
          ) : null}
          {columns.cheaper ? (
            <Card card={columns.cheaper} title="Дешевле из рассмотренных" decisionId={decisionId} open={open} onToggle={toggle}
              vetoRoles={roles(columns.cheaper.candidate_id)} />
          ) : (
            <div className="chc__card chc__card--none">
              <span className="chc__title">Дешевле</span>
              <p className="chc__muted">{choice.cheaper_note ?? "Более дешёвого варианта не передано."}</p>
            </div>
          )}
        </div>
      ) : null}

      {refused && choice.candidates.length === 0 ? (
        <p className="chc__muted">Кандидаты не рассчитывались: отказ произошёл до поиска планов.</p>
      ) : null}

      {(refused ? choice.candidates : columns.others).length > 0 ? (
        <div className="chc__others">
          <button type="button" className="chc__more" aria-expanded={showOthers || refused}
            onClick={() => setShowOthers((v) => !v)} hidden={refused}>
            Другие рассмотренные варианты ({columns.others.length})
          </button>
          {showOthers || refused ? (
            <div className="chc__cols chc__cols--others">
              {(refused ? choice.candidates : columns.others).map((card) => (
                <Card key={card.candidate_id} card={card} title="Вариант" decisionId={decisionId} open={open} onToggle={toggle}
                  vetoRoles={roles(card.candidate_id)} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {choice.agents ? (
        <p className="chc__note">
          Агенты: исключили вето {choice.agents.vetoed.length}, ограничений {choice.agents.constraints.length}.{" "}
          {choice.agents.legacy_excluded
            ? <>Влияние на выбор установлено: план ядра <code>{choice.agents.legacy_plan_id}</code> исключён агентами.</>
            : "Влияние на выбор не установлено: выбор ядра агентами не исключён."}
        </p>
      ) : null}

      <p className="chc__note">
        {choice.pool.scope} Рассчитано вариантов: {choice.pool.examined}; в финальном сравнении: {choice.pool.admissible_final}
        {choice.pool.allowed_by_agents !== undefined ? `; допущено агентами: ${choice.pool.allowed_by_agents}` : ""}.
        {choice.cheaper_count > 0 ? ` Дешевле выбранного среди рассчитанных: ${choice.cheaper_count}.` : ""}
      </p>
      <p className="chc__note">{choice.rule} Жёсткие пределы не ослабляются ради прохождения проверки.</p>

      {onChangeCondition ? (
        <p className="chc__act">
          <button type="button" className="chc__btn" onClick={onChangeCondition}>Изменить условие</button>
          <span className="chc__muted">
            Открывает «Что изменится, если…». После изменения весь расчёт выполняется заново — снятие отказа не гарантируется.
          </span>
        </p>
      ) : null}
    </section>
  );
}
