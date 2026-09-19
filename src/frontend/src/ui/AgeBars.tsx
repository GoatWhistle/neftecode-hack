import type { SourceVerdict } from "../types";
import { isNumber, num } from "../format";

function Row({ source }: { source: SourceVerdict }) {
  const age = source.age_hours;
  const max = source.max_age_hours;
  const measurable = isNumber(age) && isNumber(max) && max > 0;
  const ratio = measurable ? (age / max) * 100 : 0;
  const over = measurable && ratio > 100;
  const times = measurable ? age / max : 0;
  const share = Math.min(100, ratio);
  const overText = over
    ? times >= 2
      ? `просрочен в ${num(times, 1)} раза: старше предела на ${num(age - max, 2)} ч`
      : `просрочен: старше предела на ${num(age - max, 2)} ч`
    : "";

  return (
    <li className={`ages__row ${over ? "ages__row--over" : ""}`}>
      <span className="ages__name">{source.name}</span>
      <span className="ages__bar">
        {measurable ? (
          <span className="ages__track" role="img"
            aria-label={`${source.name}: возраст ${num(age, 2)} ч из ${num(max, 2)} ч предела${over ? `, ${overText}` : ""}`}>
            <span className={`ages__fill ${over ? "ages__fill--over" : ""}`} style={{ width: `${share}%` }} />
            {over ? <span className="ages__overflow" aria-hidden="true" /> : null}
          </span>
        ) : (
          <span className="ages__none">предел возраста не передавался</span>
        )}
      </span>
      <span className="ages__value">
        {measurable ? (
          <>
            {num(age, 2)} ч из {num(max, 2)} ч
            <span className={`ages__share ${over ? "ages__share--over" : ""}`}>
              {over ? `${num(ratio, 0)} % предела — ${overText}` : `${num(ratio, 0)} % предела`}
            </span>
          </>
        ) : isNumber(age) ? (
          `${num(age, 2)} ч, предел неизвестен`
        ) : (
          "возраст не передавался"
        )}
      </span>
    </li>
  );
}

export interface AgeBarsProps {
  sources: SourceVerdict[];
}

export function AgeBars({ sources }: AgeBarsProps) {
  if (sources.length === 0) return null;
  const scaled = sources.filter((item) => isNumber(item.age_hours) && isNumber(item.max_age_hours));
  return (
    <div className="ages">
      <p className="ages__head">Возраст замера против своего предела годности</p>
      <ul className="ages__list">
        {sources.map((source) => (
          <Row key={source.name} source={source} />
        ))}
      </ul>
      {scaled.length > 1 ? (
        <p className="ages__foot">
          Каждая полоса нормирована по собственному пределу, а не по общей оси времени: у источников
          пределы различаются в десятки раз, и на единой оси короткий предел схлопнулся бы в точку.
          Сравнивать здесь надо доли, а не длины в часах. Полоса упирается в предел и дальше не растёт,
          поэтому у просроченного замера длина полосы ничего не говорит о величине просрочки — её
          называет подпись: сколько процентов предела и во сколько раз он превышен.
        </p>
      ) : null}
    </div>
  );
}
