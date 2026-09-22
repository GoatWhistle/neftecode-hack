import { useId } from "react";
import type { RunState } from "../../run/types";
import type { ResearchSummary } from "./research";
import { passportModel } from "./model";
import type { InfluenceRef, PassportRow, PassportSection } from "./model";
import "./passport.css";

export interface EvidencePassportProps {
  /** Завершённый прогон или открытая запись: паспорт строится только из него. */
  run: RunState;
  /** Необязательная версионированная сводка исследования (neftecode.research-summary/1). */
  research?: ResearchSummary | null;
  /** Доказанные трассой связи ограничения с отсевом/итогом, ключ — constraintKey(). */
  influenceRefs?: Record<string, InfluenceRef>;
}

const PRINT_FLAG = "evidence-passport";

/** Печать только паспорта: остальная страница скрывается правилами passport.css на время печати. */
export function printPassport(): void {
  const root = document.documentElement;
  root.dataset.print = PRINT_FLAG;
  const clear = () => {
    if (root.dataset.print === PRINT_FLAG) delete root.dataset.print;
    window.removeEventListener("afterprint", clear);
  };
  window.addEventListener("afterprint", clear);
  try {
    window.print();
  } finally {
    // В браузерах без afterprint (и в jsdom) флаг не должен остаться после печати.
    setTimeout(clear, 0);
  }
}

function Rows({ rows }: { rows: PassportRow[] }) {
  return (
    <dl className="evp__rows">
      {rows.map((item) => (
        <div key={item.key} className={`evp__row evp__row--${item.tone}`} data-key={item.key}>
          <dt>{item.label}</dt>
          <dd>
            <span className="evp__value">{item.value}</span>
            <code className="evp__src">{item.source}</code>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Notes({ section }: { section: PassportSection }) {
  if (section.notes.length === 0) return null;
  return (
    <ul className="evp__notes">
      {section.notes.map((note) => <li key={note}>{note}</li>)}
    </ul>
  );
}

export function EvidencePassport({ run, research = null, influenceRefs = {} }: EvidencePassportProps) {
  const titleId = useId();
  const model = passportModel({ run, research, influenceRefs });
  if (model === null) return null;
  const { mark, input, verified, agents } = model;

  return (
    <section className="evp" aria-labelledby={titleId} data-origin={mark.origin}>
      <header className="evp__head">
        <div>
          <h3 className="evp__title" id={titleId}>Паспорт доказательств</h3>
          <p className="evp__mark">{mark.text}</p>
          <p className="evp__scenario">{mark.decision} · {mark.scenario}</p>
        </div>
        <button type="button" className="evp__print" onClick={printPassport}>Печать паспорта</button>
      </header>

      <section className="evp__part" aria-label="Вход">
        <h4 className="evp__rubric">Вход: данные и применимость</h4>
        <Rows rows={input.rows} />
        <Notes section={input} />
      </section>

      <section className="evp__part" aria-label="Проверено" data-link={verified.link ?? "none"}>
        <h4 className="evp__rubric">Проверено исследованием</h4>
        {verified.available ? <Rows rows={verified.rows} /> : null}
        <Notes section={verified} />
      </section>

      <section className="evp__part" aria-label="Агенты" data-mode={agents.mode}>
        <h4 className="evp__rubric">Агенты в этом расчёте</h4>
        <Rows rows={agents.rows} />
        {agents.roles.length > 0 ? (
          <table className="evp__table">
            <caption>Роли</caption>
            <thead>
              <tr><th scope="col">Роль</th><th scope="col">Состояние</th><th scope="col">Мнение</th><th scope="col">Что изменилось</th></tr>
            </thead>
            <tbody>
              {agents.roles.map((role) => (
                <tr key={role.key} className={role.invalid ? "evp__tr--warn" : ""}>
                  <th scope="row">{role.title}</th>
                  <td>{role.state}</td>
                  <td>{role.validity}</td>
                  <td>{role.effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {agents.constraints.length > 0 ? (
          <table className="evp__table">
            <caption>Ограничения</caption>
            <thead>
              <tr><th scope="col">Роль</th><th scope="col">Ограничение</th><th scope="col">Статус</th><th scope="col">Влияние на выбор</th></tr>
            </thead>
            <tbody>
              {agents.constraints.map((line) => (
                <tr key={line.key}>
                  <td>{line.role}</td>
                  <td>{line.label}{line.detail ? <> <code>{line.detail}</code></> : null}</td>
                  <td>{line.applied ? "применено" : "предложено"}</td>
                  <td>{line.influence.href
                    ? <a href={line.influence.href}>{line.influence.text}</a>
                    : line.influence.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        <Notes section={agents} />
      </section>

      {research ? (
        <footer className="evp__foot">
          Источники исследования: {research.sources.map((item) => (
            <code key={item.path}>{item.path} · sha256 {item.sha256.slice(0, 12)}</code>
          ))} · протокол <code>{research.protocol}</code> · сводка <code>{research.document}</code>
        </footer>
      ) : null}
    </section>
  );
}
