import { isNumber, num, termLabel } from "../format";
import type { SeverityFactors } from "../types";
import { Note } from "./Primitives";

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
      <p className="severity__head">
        Из чего собрана тяжесть режима: {num(factors.index, 3)}
      </p>
      <ul className="severity__list">
        {list.map((part) => (
          <li key={part.key} className="severity__row">
            <span className="severity__name">{part.label}</span>
            <span className="severity__bar">
              <span className="severity__track">
                <span
                  className="severity__fill"
                  style={{ width: allZero ? "0%" : `${(Math.abs(part.product) / widest) * 100}%` }}
                />
              </span>
            </span>
            <span className="severity__value">
              {num(part.term, 3)} × {num(part.weight, 2)} = <b>{num(part.product, 3)}</b>
            </span>
          </li>
        ))}
      </ul>
      {allZero ? (
        <p className="severity__zero">
          Оба слагаемых нулевые, и сумма их весов ничего не прибавляет: индекс равен{" "}
          {num(factors.index, 3)}. Режим не превышает опорных значений ни по температуре, ни по расходу,
          поэтому полосы имеют нулевую длину. Это и есть результат расчёта: минимальной видимой длины
          полосам здесь не выдано, иначе ноль выглядел бы как небольшая величина.
        </p>
      ) : (
        <p className="severity__foot">
          Длина полосы — это слагаемое, умноженное на свой вес; общая шкала здесь законна, потому что обе
          величины безразмерны и складываются в индекс.
          {matches ? ` Их сумма ${num(sum, 3)} и есть показанный индекс.` : ` Их сумма — ${num(sum, 3)}, и с показанным индексом она не сходится: расхождение считает сервер, здесь оно не сглажено.`}
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
      {factors.scope ? <Note>{factors.scope}</Note> : null}
    </div>
  );
}
