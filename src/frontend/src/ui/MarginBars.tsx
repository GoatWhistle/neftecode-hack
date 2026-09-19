import { isNumber, num } from "../format";
import type { Statement } from "../types";

export interface MarginSpec {
  topic: string;
  label: string;
  unit: string;
  direction: "below" | "above" | "between";
  digits: number;
}

const SPECS: MarginSpec[] = [
  { topic: "sulfur_mgkg", label: "Сера", unit: "мг/кг", direction: "below", digits: 2 },
  { topic: "t95_c", label: "T95", unit: "°C", direction: "below", digits: 1 },
  { topic: "cetane_number", label: "Цетановое число", unit: "", direction: "above", digits: 2 },
  { topic: "density_kgm3", label: "Плотность", unit: "кг/м³", direction: "between", digits: 1 }
];

interface Row {
  spec: MarginSpec;
  value: number;
  low: number | null;
  high: number | null;
  detail: string;
}

function limitOf(statement: Statement | undefined): number | null {
  if (!statement) return null;
  const scenario = statement.evidence.find((item) => item.kind === "scenario");
  return isNumber(scenario?.value) ? scenario.value : null;
}

export function buildRows(statements: Statement[]): Row[] {
  const byTopic = new Map(statements.map((item) => [item.topic, item]));
  const rows: Row[] = [];
  for (const spec of SPECS) {
    if (spec.direction === "between") {
      const lowStatement = byTopic.get("density_min_kgm3");
      const highStatement = byTopic.get("density_max_kgm3");
      const low = limitOf(lowStatement);
      const high = limitOf(highStatement);
      const value = lowStatement?.value ?? highStatement?.value ?? null;
      if (!isNumber(value) || (low === null && high === null)) continue;
      rows.push({ spec, value, low, high, detail: lowStatement?.text ?? highStatement?.text ?? "" });
      continue;
    }
    const statement = byTopic.get(spec.topic);
    const limit = limitOf(statement);
    if (!statement || !isNumber(statement.value) || limit === null) continue;
    rows.push({
      spec,
      value: statement.value,
      low: spec.direction === "above" ? limit : null,
      high: spec.direction === "below" ? limit : null,
      detail: statement.text
    });
  }
  return rows;
}

const TRACK = 100;

function window(value: number, low: number | null, high: number | null): [number, number] {
  const points = [value, low, high].filter(isNumber);
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const pad = Math.max((hi - lo) * 0.45, Math.abs(hi) * 0.02, 1e-6);
  return [lo - pad, hi + pad];
}

function position(value: number, from: number, to: number): number {
  const span = to - from || 1;
  return Math.max(0, Math.min(TRACK, ((value - from) / span) * TRACK));
}

function Bar({ row }: { row: Row }) {
  const { spec, value, low, high } = row;
  const [from, to] = window(value, low, high);
  const mark = position(value, from, to);
  const lowMark = low === null ? null : position(low, from, to);
  const highMark = high === null ? null : position(high, from, to);
  const ok =
    (low === null || value >= low) && (high === null || value <= high);
  const caption =
    spec.direction === "between"
      ? `${num(value, spec.digits)} между ${num(low, spec.digits)} и ${num(high, spec.digits)}`
      : spec.direction === "below"
        ? `${num(value, spec.digits)} из ${num(high, spec.digits)}`
        : `${num(value, spec.digits)} при не ниже ${num(low, spec.digits)}`;

  return (
    <li className="margins__row">
      <span className="margins__name">
        {spec.label}
        {spec.unit ? <span className="margins__unit">{spec.unit}</span> : null}
      </span>
      <span className="margins__track" role="img" aria-label={`${spec.label}: ${caption}`}>
        <svg viewBox={`0 0 ${TRACK} 22`} preserveAspectRatio="none" className="margins__svg" aria-hidden="true">
          <line className="margins__axis" x1="0" x2={TRACK} y1="16" y2="16" />
          {lowMark === null ? null : (
            <line className="margins__bound" x1={lowMark} x2={lowMark} y1="4" y2="20" />
          )}
          {highMark === null ? null : (
            <line className="margins__bound" x1={highMark} x2={highMark} y1="4" y2="20" />
          )}
          <line
            className={`margins__span ${ok ? "" : "margins__span--fail"}`}
            x1={Math.min(mark, spec.direction === "above" ? (lowMark ?? 0) : (highMark ?? TRACK))}
            x2={Math.max(mark, spec.direction === "above" ? (lowMark ?? 0) : (highMark ?? TRACK))}
            y1="16"
            y2="16"
          />
          <polygon
            className={`margins__mark ${ok ? "" : "margins__mark--fail"}`}
            points={
              spec.direction === "above"
                ? `${mark - 3},4 ${mark + 3},4 ${mark},12`
                : `${mark - 3},12 ${mark + 3},12 ${mark},4`
            }
          />
          <title>{row.detail}</title>
        </svg>
      </span>
      <span className="margins__value">{caption}</span>
    </li>
  );
}

export interface MarginBarsProps {
  statements: Statement[];
}

export function MarginBars({ statements }: MarginBarsProps) {
  const rows = buildRows(statements);
  if (rows.length === 0) return null;
  const shownTopics = new Set<string>(["density_min_kgm3", "density_max_kgm3"]);
  for (const spec of SPECS) shownTopics.add(spec.topic);
  const rest = statements.filter((item) => !shownTopics.has(item.topic));
  return (
    <div className="margins">
      <p className="margins__head">Запасы по свойствам качества</p>
      <ul className="margins__list">
        {rows.map((row) => (
          <Bar key={row.spec.topic} row={row} />
        ))}
      </ul>
      <p className="margins__foot">
        Каждая полоса построена в своих единицах и в своём окне значений, поэтому длина отрезка
        сравнима только внутри строки: зрительно сопоставлять запас по сере с запасом по T95
        нельзя, у них разные шкалы. Отрезок — это сам запас, от значения до предела; пунктир —
        предел. Направление острия показывает, в какую сторону лежит предел: вверх — «не выше»,
        вниз — «не ниже». В единый процент «здоровья плана» свести это нельзя: единицы разные —
        мг/кг, °C, безразмерное цетановое число, кг/м³, — такого числа никто не считал, и оно
        скрыло бы, по какому свойству запас тоньше.
      </p>
      {rest.length > 0 ? (
        <p className="margins__rest">
          Здесь показаны запасы только по свойствам продукта — их {rows.length}. Расчёт передал ещё{" "}
          {rest.length} утверждений другого рода, и в эти полосы они не попали: запасы по уставкам
          оборудования, производительность, выпуск, стоимость, тяжесть режима, запаздывание отклика,
          проекция за горизонт. Их темы: {rest.map((item) => item.topic).join(", ")}. Полностью они лежат
          в JSON ниже, а запасы по уставкам и отгрузке показаны отдельными полосами на этапе «Gate».
        </p>
      ) : null}
    </div>
  );
}
