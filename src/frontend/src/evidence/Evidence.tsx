import { limitRows, limitsSummary } from "./limits";
import { Empty } from "../ui/Primitives";
import type { ScreenPayload } from "../types";

export interface EvidenceProps {
  payload: ScreenPayload;
}

const DIRECTION_WORD: Record<string, string> = {
  max: "не выше",
  min: "не ниже",
  unknown: "предел"
};

function plural(count: number, one: string, few: string, many: string): string {
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  const mod10 = count % 10;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function num(value: number | null, digits = 3): string {
  if (value === null || !Number.isFinite(value)) return "нет оценки";
  return value.toFixed(digits).replace(/\.?0+$/, "");
}

function Sources({ payload }: EvidenceProps) {
  const sources = payload.sources ?? [];
  if (sources.length === 0) return <Empty>Источники в результате не переданы.</Empty>;
  return (
    <table className="ev__table">
      <caption>Источники качества на момент решения</caption>
      <thead>
        <tr>
          <th scope="col">Источник</th>
          <th scope="col">Значение</th>
          <th scope="col">Возраст</th>
          <th scope="col">Пригоден</th>
        </tr>
      </thead>
      <tbody>
        {sources.map((item) => (
          <tr key={item.name}>
            <th scope="row">{item.name}</th>
            <td>{item.value === null || item.value === undefined ? "нет оценки" : num(item.value, 2)}</td>
            <td>{item.age_hours === null || item.age_hours === undefined ? "нет оценки" : `${num(item.age_hours, 2)} ч`}</td>
            <td className={item.usable ? "ev__ok" : "ev__bad"}>{item.usable ? "да" : "нет"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Limits({ payload }: EvidenceProps) {
  const rows = limitRows(payload);
  const summary = limitsSummary(payload);
  if (rows.length === 0) return <Empty>Протокол проверок не передавался: поиск плана не дошёл до Gate.</Empty>;
  return (
    <>
      {summary ? (
        <p className="ev__lead">
          В протоколе {summary.checks} {plural(summary.checks, "запись", "записи", "записей")} — это{" "}
          {summary.unique} {plural(summary.unique, "ограничение", "ограничения", "ограничений")}, каждое
          проверено на нескольких моментах горизонта. Ниже по одному худшему запасу на ограничение.
        </p>
      ) : null}
      <table className="ev__table">
        <caption>Ограничения по худшему запасу</caption>
        <thead>
          <tr>
            <th scope="col">Ограничение</th>
            <th scope="col">Наблюдалось</th>
            <th scope="col">Предел</th>
            <th scope="col">Запас</th>
            <th scope="col">Момент</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={row.status === "pass" ? "" : "ev__row--warn"}>
              <th scope="row">
                <span className="ev__id">{row.id}</span>
                <span className="ev__times">{DIRECTION_WORD[row.direction]} · записей {row.times}</span>
              </th>
              <td>{num(row.observed, 2)}</td>
              <td>{num(row.limit, 2)}</td>
              <td className={row.margin !== null && row.margin < 0 ? "ev__bad" : ""}>{num(row.margin, 3)}</td>
              <td>{row.atHours === null ? "нет отметки" : `${num(row.atHours, 1)} ч`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Stress({ payload }: EvidenceProps) {
  const robustness = payload.decision.robustness;
  const results = robustness?.results ?? [];
  if (!robustness || results.length === 0) {
    return <Empty>Стресс-проверки не проводились или их исходы не передавались.</Empty>;
  }
  return (
    <>
      <p className="ev__lead">
        Заявлено {robustness.perturbations_declared}, посчитано {robustness.perturbations_evaluated},
        выдержало {robustness.held}, нарушило {robustness.violated}, неприменимо {robustness.not_applicable}.
        Это перечень посчитанных отклонений, а не вероятность безопасности.
      </p>
      <ul className="ev__list">
        {results.map((item, index) => (
          <li key={`${item.perturbation}-${index}`} className={item.outcome === "holds" ? "" : "ev__row--warn"}>
            <span className="ev__id">{item.perturbation}</span>
            <span className={item.outcome === "holds" ? "ev__ok" : "ev__bad"}>
              {item.outcome === "holds" ? "выдержал" : item.outcome === "violates" ? "нарушил" : item.outcome}
            </span>
            {item.reason ? <span className="ev__times">{item.reason}</span> : null}
          </li>
        ))}
      </ul>
    </>
  );
}

function Horizon({ payload }: EvidenceProps) {
  const look = payload.decision.lookahead;
  if (!look || look.available !== true) {
    return <Empty>Прогноз за горизонтом не считался или его результат не передавался.</Empty>;
  }
  const selected = look.selected;
  return (
    <>
      <p className="ev__lead">
        Горизонт {num(look.lookahead_hours, 0)} ч, запас реакции {num(look.min_reaction_hours, 0)} ч.
        Числовых точек траектории сервер не передаёт, поэтому кривая не строится.
      </p>
      <dl className="ev__pairs">
        <div>
          <dt>Ограничение</dt>
          <dd>{selected?.constraint ?? "нет оценки"}</dd>
        </div>
        <div>
          <dt>До нарушения</dt>
          <dd>{selected?.hours_to_violation === null || selected?.hours_to_violation === undefined
            ? "нарушений не видно" : `${num(selected.hours_to_violation, 1)} ч`}</dd>
        </div>
        <div>
          <dt>Запас компонента кончается</dt>
          <dd>{selected?.stock_ends_at_hours === null || selected?.stock_ends_at_hours === undefined
            ? "нет оценки" : `${num(selected.stock_ends_at_hours, 1)} ч`}</dd>
        </div>
      </dl>
    </>
  );
}

export function Evidence({ payload }: EvidenceProps) {
  return (
    <section className="ev" aria-labelledby="ev-title">
      <p className="ev__rubric" id="ev-title">Доказательства</p>
      <details className="ev__block">
        <summary>Данные и источники</summary>
        <Sources payload={payload} />
      </details>
      <details className="ev__block">
        <summary>Прогноз за горизонтом</summary>
        <Horizon payload={payload} />
      </details>
      <details className="ev__block">
        <summary>Ограничения и проверки</summary>
        <Limits payload={payload} />
      </details>
      <details className="ev__block">
        <summary>Устойчивость к отклонениям</summary>
        <Stress payload={payload} />
      </details>
    </section>
  );
}
