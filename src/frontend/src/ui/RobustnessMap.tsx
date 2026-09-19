import type { Robustness, RobustnessResult } from "../types";
import { isNumber, num } from "../format";

const SPAN = 100;

function deviation(factor: number | null | undefined): number | null {
  return isNumber(factor) ? factor - 1 : null;
}

function reach(results: RobustnessResult[]): number {
  const spread = results
    .filter((item) => item.outcome !== "not_applicable")
    .map((item) => deviation(item.factor))
    .filter(isNumber)
    .map(Math.abs);
  return spread.length === 0 ? 0.5 : Math.max(...spread) * 1.25;
}

function signText(outcome: string): string {
  if (outcome === "holds") return "выдержал";
  if (outcome === "violates") return "нарушил";
  return "неприменимо";
}

function Sign({ outcome }: { outcome: string }) {
  if (outcome === "violates") {
    return (
      <svg viewBox="0 0 14 14" className="robust__sign robust__sign--fail" aria-hidden="true">
        <line x1="3" y1="3" x2="11" y2="11" />
        <line x1="11" y1="3" x2="3" y2="11" />
      </svg>
    );
  }
  if (outcome === "holds") {
    return (
      <svg viewBox="0 0 14 14" className="robust__sign robust__sign--pass" aria-hidden="true">
        <circle cx="7" cy="7" r="4.5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 14 14" className="robust__sign robust__sign--muted" aria-hidden="true">
      <circle cx="7" cy="7" r="4" fill="none" />
    </svg>
  );
}

function Row({ item, limit }: { item: RobustnessResult; limit: number }) {
  const offset = deviation(item.factor);
  const centre = SPAN / 2;
  const applied = item.outcome !== "not_applicable";
  const mark = offset === null ? null : centre + (offset / limit) * (SPAN / 2);
  const label =
    offset === null
      ? "коэффициент не передавался"
      : `${offset > 0 ? "+" : ""}${num(offset * 100, 0)} %`;

  return (
    <li className={`robust__row robust__row--${item.outcome}`}>
      <span className="robust__name">
        <Sign outcome={item.outcome} />
        {item.perturbation}
      </span>
      <span className="robust__scale">
        {applied ? (
          <svg viewBox={`0 0 ${SPAN} 18`} preserveAspectRatio="none" className="robust__svg" role="img"
            aria-label={`${item.perturbation}: отклонение ${label}, ${signText(item.outcome)}`}>
            <line className="robust__axis" x1="0" x2={SPAN} y1="9" y2="9" />
            <line className="robust__zero" x1={centre} x2={centre} y1="2" y2="16" />
            {mark === null ? null : (
              <>
                <line className="robust__reach" x1={centre} x2={mark} y1="9" y2="9" />
                <circle className="robust__dot" cx={mark} cy="9" r="2.6" />
              </>
            )}
          </svg>
        ) : (
          <span className="robust__noscale">к плану не применялось</span>
        )}
      </span>
      <span className="robust__factor">{applied ? label : `объявлено ${label}`}</span>
      <span className="robust__outcome">
        {signText(item.outcome)}
        {item.reason ? <span className="robust__reason">{item.reason}</span> : null}
        {isNumber(item.cost_per_tonne) ? (
          <span className="robust__cost">стоимость тонны {num(item.cost_per_tonne, 4)}</span>
        ) : null}
      </span>
      <span className="robust__path">
        <code>{item.path}</code>
      </span>
    </li>
  );
}

export interface RobustnessMapProps {
  robustness: Robustness;
}

export function RobustnessMap({ robustness }: RobustnessMapProps) {
  const results = robustness.results ?? [];
  if (results.length === 0) return null;
  const limit = reach(results);
  const skipped = results.filter((item) => item.outcome === "not_applicable").length;
  const costs = results.map((item) => item.cost_per_tonne).filter(isNumber);
  const flat = costs.length > 1 && Math.max(...costs) - Math.min(...costs) < 1e-9;
  const production = results.map((item) => item.production_t).filter(isNumber);
  const flatProduction = production.length > 1 && Math.max(...production) - Math.min(...production) < 1e-9;

  return (
    <div className="robust">
      <p className="robust__head">
        Возмущения поимённо: {results.length} объявлено, {robustness.perturbations_evaluated} оценено
      </p>
      <ul className="robust__list">
        {results.map((item) => (
          <Row key={`${item.perturbation}-${item.path}`} item={item} limit={limit} />
        ))}
      </ul>
      <p className="robust__scalehint">
        Вертикаль в середине каждой шкалы — исходное значение без возмущения; отметка показывает,
        насколько параметр сдвинут относительно него.
        {skipped > 0
          ? ` У ${skipped} возмущений шкалы нет вовсе: они к плану не применялись, оценки отклонения по ним никто не получал, и отметка на шкале выдала бы их за проверенные. Объявленный коэффициент назван словами, причина — в строке рядом.`
          : ""}
      </p>
      {flatProduction ? (
        <p className="robust__degenerate">
          Выпуск во всех оценённых возмущениях один и тот же — {num(production[0], 1)} т. Разброса нет,
          и растягивать шкалу, чтобы он казался заметным, здесь нечего.
        </p>
      ) : null}
      {flat ? (
        <p className="robust__degenerate">
          Стоимость тонны совпадает в части возмущений до последнего знака: это совпадение расчёта,
          а не сглаживание отображения.
        </p>
      ) : null}
      {robustness.limits?.length ? (
        <div className="limits">
          <p className="limits__head">Чего эта проверка не утверждает</p>
          <ul className="limits__list">
            {robustness.limits.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
