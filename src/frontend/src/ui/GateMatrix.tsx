import type { CheckStatus, GateCheck } from "../types";
import { familyOf, isNumber, num } from "../format";

const CELL = 20;
const ROW = 17;
const LABEL_MIN = 120;
const LABEL_MAX = 300;
const LABEL_CHAR = 5.4;
const LABEL_PAD = 18;
const HEAD = 26;
const OUTSIDE_GAP = 14;

interface MatrixRow {
  id: string;
  family: string;
  cells: Map<string, GateCheck>;
  outside: GateCheck | null;
}

function key(time: number): string {
  return time.toFixed(2);
}

export function layout(checks: GateCheck[]): { rows: MatrixRow[]; times: number[]; hasOutside: boolean } {
  const times = [...new Set(checks.filter((c) => isNumber(c.time_hours)).map((c) => c.time_hours as number))].sort(
    (a, b) => a - b
  );
  const map = new Map<string, MatrixRow>();
  for (const check of checks) {
    const row =
      map.get(check.constraint_id) ??
      { id: check.constraint_id, family: familyOf(check.constraint_id), cells: new Map(), outside: null };
    if (isNumber(check.time_hours)) row.cells.set(key(check.time_hours), check);
    else row.outside = check;
    map.set(check.constraint_id, row);
  }
  const rows = [...map.values()];
  const hasOutside = rows.some((row) => row.outside !== null);
  return { rows, times, hasOutside };
}

function tip(check: GateCheck): string {
  const head = `${check.constraint_id}: ${
    check.status === "pass" ? "пройдено" : check.status === "fail" ? "нарушено" : "не проверено"
  }`;
  const nums =
    isNumber(check.observed) || isNumber(check.limit)
      ? ` — наблюдалось ${num(check.observed, 3)}, предел ${num(check.limit, 3)}`
      : "";
  const when = isNumber(check.time_hours) ? `, момент ${num(check.time_hours, 1)} ч` : ", вне горизонта";
  return `${head}${nums}${when}${check.reason ? `. ${check.reason}` : ""}`;
}

function Cell({ check, x, y }: { check: GateCheck | null | undefined; x: number; y: number }) {
  if (!check) return null;
  const status: CheckStatus = check.status;
  return (
    <g className={`matrix__cell matrix__cell--${status}`}>
      <rect
        x={x + 2}
        y={y + 2}
        width={CELL - 4}
        height={ROW - 4}
        rx="1.5"
        fill={status === "fail" ? "var(--fail)" : status === "unknown" ? "url(#matrix-unknown)" : "none"}
      />
      <title>{tip(check)}</title>
    </g>
  );
}

export interface GateMatrixProps {
  checks: GateCheck[];
}

function labelWidth(rows: MatrixRow[]): number {
  const longest = rows.reduce((acc, row) => Math.max(acc, row.id.length), 0);
  return Math.min(LABEL_MAX, Math.max(LABEL_MIN, Math.ceil(longest * LABEL_CHAR) + LABEL_PAD));
}

export function GateMatrix({ checks }: GateMatrixProps) {
  const { rows, times, hasOutside } = layout(checks);
  if (rows.length === 0) return null;

  const labelW = labelWidth(rows);
  const gridW = times.length * CELL;
  const outsideX = labelW + gridW + OUTSIDE_GAP;
  const width = outsideX + (hasOutside ? CELL : 0) + 4;
  const height = HEAD + rows.length * ROW + 6;

  let previous = "";
  return (
    <figure className="matrix">
      <svg viewBox={`0 0 ${width} ${height}`} className="matrix__svg" role="img"
        aria-label={`Матрица проверок Gate: ${rows.length} ограничений на ${times.length} моментов времени`}>
        <defs>
          <pattern id="matrix-unknown" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="4" stroke="var(--unknown)" strokeWidth="1.6" />
          </pattern>
        </defs>
        {times.map((time, column) => (
          <text key={time} className="matrix__axis" x={labelW + column * CELL + CELL / 2} y={HEAD - 10}
            textAnchor="middle">
            {num(time, 1)}
          </text>
        ))}
        {hasOutside ? (
          <text className="matrix__axis matrix__axis--outside" x={outsideX + CELL / 2} y={HEAD - 10} textAnchor="middle">
            вне
          </text>
        ) : null}
        {rows.map((row, line) => {
          const y = HEAD + line * ROW;
          const seam = previous !== "" && row.family !== previous;
          previous = row.family;
          return (
            <g key={row.id}>
              {seam ? <line className="matrix__seam" x1="6" x2={width - 4} y1={y} y2={y} /> : null}
              <text className="matrix__label" x={labelW - 10} y={y + ROW / 2 + 4} textAnchor="end">
                {row.id}
              </text>
              {times.map((time, column) => (
                <Cell key={time} check={row.cells.get(key(time))} x={labelW + column * CELL} y={y} />
              ))}
              {row.outside ? <Cell check={row.outside} x={outsideX} y={y} /> : null}
            </g>
          );
        })}
      </svg>
      <figcaption className="matrix__caption">
        Строка — ограничение, колонка — момент горизонта в часах. Тонкая рамка — пройдено, сплошная
        заливка — нарушено, штриховка — не проверено. Колонка «вне» держит проверки, у которых
        момента времени нет вовсе: они относятся к плану целиком, а не к шагу, и размазывать их по
        часам было бы выдумкой.
      </figcaption>
    </figure>
  );
}
