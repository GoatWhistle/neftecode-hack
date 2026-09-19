import type { LookaheadOffspec } from "../types";
import { isNumber, num, percent } from "../format";
import { Field, Fields, Note } from "./Primitives";

function CostBar({ label, value, span }: { label: string; value: number; span: number }) {
  const share = span > 0 ? (value / span) * 100 : 0;
  return (
    <li className="offspec__row">
      <span className="offspec__label">{label}</span>
      <span className="offspec__bar" role="img" aria-label={`${label}: ${num(value, 4)} у.е. за тонну`}>
        <span className="offspec__fill" style={{ width: `${share}%` }} />
      </span>
      <span className="offspec__value">{num(value, 4)} у.е./т</span>
    </li>
  );
}

export interface OffspecBlockProps {
  offspec: LookaheadOffspec;
}

export function OffspecBlock({ offspec }: OffspecBlockProps) {
  const hold = offspec.hold_cost_per_tonne;
  const plan = offspec.plan_cost_per_tonne;
  const delta = offspec.delta_cost_per_tonne;
  const pair = [hold, plan].filter(isNumber);
  const span = pair.length > 0 ? Math.max(...pair) * 1.1 : 0;
  const same = isNumber(delta) && Math.abs(delta) < 1e-9;

  return (
    <div className="offspec">
      <p className="offspec__head">Некондиция: сохранение режима против выбранного плана</p>

      {pair.length === 2 ? (
        <ul className="offspec__list">
          <CostBar label="Сохранить режим" value={hold as number} span={span} />
          <CostBar label="Выбранный план" value={plan as number} span={span} />
        </ul>
      ) : (
        <p className="offspec__degenerate">Стоимости для сравнения не переданы обе, полос нет.</p>
      )}

      <p className={`offspec__delta ${same ? "offspec__delta--flat" : ""}`}>
        {same
          ? "Разницы в стоимости нет: обе величины совпадают до последнего знака, поэтому полосы равны. Масштаб не подобран так, чтобы разница казалась заметной — её нет."
          : `Разница: ${num(delta, 4)} у.е. за тонну, всего ${num(offspec.plan_extra_cost, 3)} у.е. за горизонт.`}
      </p>

      <Fields>
        <Field label="Доля некондиции">
          {isNumber(offspec.share) ? percent(offspec.share) : "не передавалась"}
          {offspec.share_source ? ` (источник: ${offspec.share_source})` : ""}
        </Field>
        <Field label="Запас основного компонента">
          {isNumber(offspec.main_stock_t) ? `${num(offspec.main_stock_t, 1)} т` : "не передавался"}
          {offspec.main_tank ? <code>{offspec.main_tank}</code> : null}
        </Field>
        <Field label="Цена основного компонента">
          {isNumber(offspec.main_price_per_t) ? `${num(offspec.main_price_per_t, 3)} у.е./т` : "не передавалась"}
        </Field>
        <Field label="Стоимость переработки">
          {isNumber(offspec.rework_cost) ? `${num(offspec.rework_cost, 1)} у.е.` : "не передавалась"}
        </Field>
        <Field label="Выпуск за горизонт">
          {isNumber(offspec.production_t) ? `${num(offspec.production_t, 1)} т` : "не передавался"}
        </Field>
        <Field label="Сохранение режима допустимо">
          {offspec.hold_feasible === null || offspec.hold_feasible === undefined
            ? "не передавалось"
            : offspec.hold_feasible
              ? "да"
              : "нет"}
        </Field>
        <Field label="Влияет на допустимость">
          {offspec.affects_admissibility ? "да" : "нет — допустимость решает проверка пределов продукта"}
        </Field>
      </Fields>

      {offspec.note ? <Note>{offspec.note}</Note> : null}
    </div>
  );
}
