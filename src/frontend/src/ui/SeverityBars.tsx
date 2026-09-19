import { isNumber, num, termLabel } from "../format";
import type { SeverityFactors } from "../types";

interface Part {
  key: string;
  label: string;
  term: number;
  weight: number;
  product: number;
}

function parts(factors: SeverityFactors): Part[] {
  return Object.entries(factors.terms ?? {}).map(([key, term]) => {
    const weight = factors.weights?.[key];
    const safeTerm = isNumber(term) ? term : 0;
    const safeWeight = isNumber(weight) ? weight : 0;
    return {
      key,
      label: termLabel(key),
      term: safeTerm,
      weight: safeWeight,
      product: safeTerm * safeWeight
    };
  });
}

function Row({ part, widest }: { part: Part; widest: number }) {
  const zero = part.product === 0;
  const width = widest === 0 ? 0 : (Math.abs(part.product) / widest) * 100;
  return (
    <li className={`severity__row${zero ? " severity__row--zero" : ""}`}>
      <span className="severity__name">{part.label}</span>
      <span className="severity__bar">
        {zero ? (
          <span className="severity__nil">ноль, полосы нет</span>
        ) : (
          <span className="severity__track">
            <span className="severity__fill" style={{ width: `${width}%` }} />
          </span>
        )}
      </span>
      <span className="severity__value">
        <span className="severity__factor">
          <i>превышение</i> {num(part.term, 3)}
        </span>
        <span className="severity__factor">
          <i>вес</i> {num(part.weight, 2)}
        </span>
        <span className="severity__factor severity__factor--product">
          <i>слагаемое</i> <b>{num(part.product, 3)}</b>
        </span>
      </span>
    </li>
  );
}

export interface SeverityBarsProps {
  factors: SeverityFactors;
}

export function SeverityBars({ factors }: SeverityBarsProps) {
  const list = parts(factors);
  if (list.length === 0) return null;
  const sum = list.reduce((acc, part) => acc + part.product, 0);
  const widest = Math.max(...list.map((part) => Math.abs(part.product)));
  const allZero = widest === 0;
  const index = isNumber(factors.index) ? factors.index : null;
  const matches = index === null || Math.abs(sum - index) < 1e-9;

  return (
    <div className="severity">
      <div className="severity__top">
        <h4 className="severity__head">Из чего собрана тяжесть режима</h4>
        <p className="severity__index">
          <span className="severity__index-value">{num(factors.index, 3)}</span>
          <span className="severity__index-word">
            {allZero ? "режим не превышает опорных значений" : "сумма слагаемых с их весами"}
          </span>
        </p>
      </div>

      <ul className="severity__list">
        {list.map((part) => (
          <Row key={part.key} part={part} widest={widest} />
        ))}
      </ul>

      <div className="severity__prose">
        {allZero ? (
          <p className="severity__zero">
            Оба слагаемых нулевые, и веса ничего не прибавляют: индекс равен {num(factors.index, 3)}.
            Ни по температуре, ни по расходу режим не выходит за опорные значения. Полосы нулевой длины
            не нарисованы вовсе: минимальной видимой длины нулю здесь не выдано, иначе ноль читался бы
            как небольшая величина.
          </p>
        ) : (
          <p className="severity__foot">
            Длина полосы — это превышение, умноженное на свой вес; общая шкала здесь законна, потому что
            обе величины безразмерны и складываются в индекс.
            {matches
              ? ` Их сумма ${num(sum, 3)} и есть показанный индекс.`
              : ` Их сумма — ${num(sum, 3)}, и с показанным индексом она не сходится: расхождение считает сервер, здесь оно не сглажено.`}
          </p>
        )}
        <p className="severity__refs">
          Опорная температура <b>{num(factors.reference_temp_c, 1)} °C</b>, опорный расход{" "}
          <b>{num(factors.reference_flow_m3h, 1)} м³/ч</b>
          {factors.control_range_c ? (
            <>
              , диапазон уставки{" "}
              <b>
                {num(factors.control_range_c[0], 0)}–{num(factors.control_range_c[1], 0)} °C
              </b>
            </>
          ) : null}
          .
        </p>
        {factors.scope ? <p className="severity__scope">{factors.scope}</p> : null}
      </div>
    </div>
  );
}
