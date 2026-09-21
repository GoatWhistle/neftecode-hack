import { useId, useState } from "react";
import type { RunState } from "../run/types";
import { contributionModel } from "./contribution";
import type { AgentCardModel } from "./contribution";

export interface AgentContributionProps {
  run: RunState;
}

const STEP_LABEL = ["Что проверил", "Что заключил", "Что изменилось"];

function Card({ card }: { card: AgentCardModel }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const steps = [card.checked, card.concluded, card.effect];
  const hasDetail = card.constraints.length > 0 || card.evidence.length > 0 || card.tech.length > 0;

  return (
    <article className={`acard acard--${card.tone}`}>
      <header className="acard__top">
        <h4 className="acard__title">{card.title}</h4>
        <span className="acard__state">{card.state}</span>
      </header>

      <dl className="acard__steps">
        {steps.map((text, index) => (
          <div key={STEP_LABEL[index]} className="acard__step">
            <dt>{STEP_LABEL[index]}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>

      {card.invalid ? (
        <p className="acard__flag">Не принято к исполнению</p>
      ) : null}

      {hasDetail ? (
        <>
          <button
            type="button"
            className="acard__more"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((prev) => !prev)}
          >
            <span className="acard__caret" aria-hidden="true" />
            Сообщения и доказательства
          </button>
          <div id={panelId} className="acard__panel" data-open={open ? "yes" : "no"}>
            <div className="acard__panelin">
              {card.constraints.length > 0 ? (
                <section className="acard__block">
                  <h5 className="acard__rubric">Ограничения</h5>
                  <ul className="acard__list">
                    {card.constraints.map((line) => (
                      <li key={line.key} className={line.applied ? "acon acon--applied" : "acon acon--proposed"}>
                        <span className="acon__mark">{line.applied ? "применено" : "предложено"}</span>
                        <span className="acon__label">{line.label}</span>
                        {line.detail !== null ? <code className="acon__detail">{line.detail}</code> : null}
                      </li>
                    ))}
                  </ul>
                  <p className="acard__foot">
                    «Предложено» — то, что роль запросила. «Применено» — то, что совпало с подтверждённым
                    списком <code>constraints_applied</code>. Это не одно и то же.
                  </p>
                </section>
              ) : null}

              {card.evidence.length > 0 ? (
                <section className="acard__block">
                  <h5 className="acard__rubric">Доказательства</h5>
                  <ul className="acard__list">
                    {card.evidence.map((line) => (
                      <li key={line.key} className="aev">{line.text}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {card.tech.length > 0 ? (
                <p className="acard__tech">Технические детали: {card.tech.join(" · ")}</p>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </article>
  );
}

export function AgentContribution({ run }: AgentContributionProps) {
  const model = contributionModel(run);
  const titleId = useId();

  return (
    <section className="acon-wrap" aria-labelledby={titleId}>
      <h3 className="acon-wrap__rubric" id={titleId}>Вклад агентов</h3>

      {model.absent !== null ? (
        <p className="acon-wrap__absent">{model.absent}</p>
      ) : (
        <>
          <p className="acon-wrap__lead">{model.headline}</p>
          <div className="acon-wrap__grid">
            {model.cards.map((card) => <Card key={card.key} card={card} />)}
          </div>
        </>
      )}
    </section>
  );
}
