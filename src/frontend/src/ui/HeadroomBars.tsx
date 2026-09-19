import { controlLabel, controlUnit, familyOf, isNumber, num } from "../format";
import type { GateCheck } from "../types";

const TRACK = 100;
const FAMILIES = ["control", "outflow"];

export interface HeadroomRow {
  id: string;
  label: string;
  unit: string;
  limit: number;
  worst: number;
  worstAt: number | null;
  constant: boolean;
  moments: number;
  digits: number;
}

function labelOf(id: string, names: Record<string, string>): string {
  const [head, ...rest] = id.split(".");
  const key = rest.join(".");
  if (head === "control") return controlLabel(key);
  return `${familyOf(id)}: ${names[key] ?? key}`;
}

function unitOf(id: string): string {
  const [head, ...rest] = id.split(".");
  if (head === "control") return controlUnit(rest.join("."));
  return "т/ч";
}

export function buildHeadroom(checks: GateCheck[], names: Record<string, string> = {}): HeadroomRow[] {
  const groups = new Map<string, GateCheck[]>();
  for (const check of checks) {
    const head = check.constraint_id.split(".")[0] ?? "";
    if (!FAMILIES.includes(head)) continue;
    if (!isNumber(check.observed) || !isNumber(check.limit)) continue;
    const list = groups.get(check.constraint_id) ?? [];
    list.push(check);
    groups.set(check.constraint_id, list);
  }
  const rows: HeadroomRow[] = [];
  for (const [id, list] of groups) {
    const values = list.map((check) => check.observed as number);
    const limit = Math.max(...list.map((check) => check.limit as number));
    const worstCheck = list.reduce((acc, check) =>
      (check.observed as number) > (acc.observed as number) ? check : acc
    );
    const spread = Math.max(...values) - Math.min(...values);
    const digits = Math.abs(limit) >= 100 ? 1 : 2;
    rows.push({
      id,
      label: labelOf(id, names),
      unit: unitOf(id),
      limit,
      worst: worstCheck.observed as number,
      worstAt: worstCheck.time_hours,
      constant: spread === 0,
      moments: list.length,
      digits
    });
  }
  return rows.sort((a, b) => b.worst / (b.limit || 1) - a.worst / (a.limit || 1));
}

function Row({ row }: { row: HeadroomRow }) {
  const share = row.limit > 0 ? Math.min(TRACK, Math.max(0, (row.worst / row.limit) * TRACK)) : 0;
  const over = row.worst > row.limit;
  const headroom = row.limit - row.worst;
  const caption = `${num(row.worst, row.digits)} из ${num(row.limit, row.digits)}${row.unit ? ` ${row.unit}` : ""}, запас ${num(headroom, row.digits)}`;

  return (
    <li className="headroom__row">
      <span className="headroom__name">{row.label}</span>
      <span className="headroom__bar">
        <span
          className="headroom__track"
          role="img"
          aria-label={`${row.label}: ${caption} до верхнего предела`}
        >
          <span
            className={`headroom__fill ${over ? "headroom__fill--over" : ""}`}
            style={{ width: `${share}%` }}
          />
        </span>
      </span>
      <span className="headroom__value">
        {caption}
        <span className="headroom__when">
          {row.constant
            ? `за горизонт не меняется, одно значение на все ${row.moments} моментов`
            : `худший из ${row.moments} моментов${row.worstAt === null ? "" : `, на ${num(row.worstAt, 1)} ч`}`}
        </span>
      </span>
    </li>
  );
}

export interface HeadroomBarsProps {
  checks: GateCheck[];
  names?: Record<string, string>;
}

export function HeadroomBars({ checks, names = {} }: HeadroomBarsProps) {
  const rows = buildHeadroom(checks, names);
  if (rows.length === 0) return null;
  const constant = rows.filter((row) => row.constant).length;

  return (
    <div className="headroom">
      <p className="headroom__head">Сколько свободы до предела оборудования и отгрузки</p>
      <ul className="headroom__list">
        {rows.map((row) => (
          <Row key={row.id} row={row} />
        ))}
      </ul>
      <p className="headroom__foot">
        Полоса односторонняя, и это не упрощение: в payload у этих ограничений передан только верхний
        предел. Нижней границы тут нет, поэтому коридор «от и до» не нарисован — его никто не задавал, и
        симметричная вилка была бы выдумкой. Ноль полосы — это ноль величины, а правый край — предел;
        закрашенная часть показывает, насколько близко подошло значение, незакрашенная — запас.
        {constant === rows.length
          ? ` Ни у одного из этих ограничений значение не меняется по горизонту, поэтому у каждого показано одно значение, а не повтор одинаковых полос по числу моментов.`
          : constant > 0
            ? ` У ${constant} ограничений из ${rows.length} значение не меняется по горизонту — у них показано одно значение, а не повтор одинаковых полос; у остальных взят худший момент.`
            : " У каждого ограничения взят худший момент горизонта."}{" "}
        Каждая полоса нормирована своим пределом, и длины между строками сравнивать нельзя: единицы
        разные. Полная раскладка по каждому моменту — в матрице проверок выше.
      </p>
    </div>
  );
}
