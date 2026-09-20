import { controlLabel, controlUnit, hours, num } from "../format";
import type { PlanStep, ScreenPayload } from "../types";
import { stockLine } from "../provenance";
import { humanizeReason } from "../run/orchRead";
import { Empty } from "./Primitives";
import { OriginBadge } from "./Origin";

export interface VerdictHeadProps {
  payload: ScreenPayload;
  refused: boolean;
}

// decision.scope — код из domain/shared/primitives.py: SCENARIO_SCOPE ("synthetic_scenario") или
// CONFIRMED_SCOPE ("confirmed_model"), других значений backend не производит. Независимая проверка
// нашла "synthetic_scenario" сырым текстом на основном экране.
const SCOPE_TEXT: Record<string, string> = {
  synthetic_scenario: "сценарные данные, не измерения завода",
  confirmed_model: "подтверждено детерминированной моделью"
};

export function VerdictHead({ payload, refused }: VerdictHeadProps) {
  const decision = payload.decision;
  return (
    <div className={`final__verdict ${refused ? "final__verdict--refuse" : "final__verdict--ok"}`}>
      <p className="final__kicker">Вердикт советчика</p>
      <p className="final__label">{payload.status_label}</p>
      <p className="final__reason">{humanizeReason(decision.reason)}</p>
      {decision.scope ? (
        <p className="final__scope">{SCOPE_TEXT[decision.scope] ?? decision.scope}</p>
      ) : null}
    </div>
  );
}

export interface ActionBlockProps {
  payload: ScreenPayload;
  action: PlanStep;
}

export function ActionBlock({ payload, action }: ActionBlockProps) {
  const names = payload.explanation.component_names ?? {};
  const controls = Object.entries(action.controls ?? {});
  const recipe = Object.entries(action.recipe ?? {});

  return (
    <div className="final__action">
      <p className="final__kicker">Что сделать прямо сейчас</p>
      <p className="final__when">
        Момент действия <b>{hours(action.time_hours)}</b>
      </p>
      <dl className="final__controls">
        {controls.map(([key, value]) => (
          <div key={key} className="final__control">
            <dt>{controlLabel(key)}</dt>
            <dd>
              {num(value, 1)}
              {" "}
              <span className="final__unit">{controlUnit(key)}</span>
            </dd>
            <span className="final__origin">
              <OriginBadge origin="derived" />
            </span>
          </div>
        ))}
        <div className="final__control">
          <dt>Производительность</dt>
          <dd>
            {num(action.throughput_tph, 1)}
            {" "}
            <span className="final__unit">т/ч</span>
          </dd>
          <span className="final__origin">
            <OriginBadge origin="derived" />
          </span>
        </div>
        <div className="final__control">
          <dt>Доза присадки</dt>
          <dd>
            {num(action.additive_dose, 3)}
            {" "}
            <span className="final__unit">кг/т</span>
          </dd>
          <span className="final__origin">
            <OriginBadge origin="derived" />
          </span>
        </div>
      </dl>
      {recipe.length > 0 ? (
        <div className="final__recipe">
          <p className="final__kicker">Рецепт смешения и откуда берут компоненты</p>
          <ul className="final__blend">
            {recipe.map(([key, value]) => {
              const line = stockLine(payload, key);
              return (
                <li key={key} className="final__blend-row">
                  <span className="final__blend-name">{names[key] ?? key}</span>
                  <span className="final__blend-share">{num(value, 3)}</span>
                  <span className="final__blend-stock">{line.text}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <Empty>Рецепт смешения не передавался.</Empty>
      )}
    </div>
  );
}
