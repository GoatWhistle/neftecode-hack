import { num } from "../format";

export interface TrajectoryPoint {
  time: number;
  value: number;
}

export interface TrajectoryProps {
  points: TrajectoryPoint[];
  limit: number | null;
  unit: string;
  label: string;
  digits?: number;
}

const W = 720;
const H = 240;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 34;

function stepPath(points: TrajectoryPoint[], x: (t: number) => number, y: (v: number) => number): string {
  const parts: string[] = [];
  points.forEach((point, index) => {
    const px = x(point.time).toFixed(1);
    const py = y(point.value).toFixed(1);
    if (index === 0) {
      parts.push(`M${px},${py}`);
      return;
    }
    parts.push(`H${px}`);
    parts.push(`V${py}`);
  });
  return parts.join(" ");
}

export function Trajectory({ points, limit, unit, label, digits = 3 }: TrajectoryProps) {
  if (points.length === 0) return null;

  const times = points.map((p) => p.time);
  const values = points.map((p) => p.value);
  const candidates = limit === null ? values : [...values, limit];
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const vMax = Math.max(...candidates) * 1.06;
  const vMin = Math.min(...candidates, 0);
  const spanT = tMax - tMin || 1;
  const spanV = vMax - vMin || 1;

  const x = (t: number) => PAD_L + ((t - tMin) / spanT) * (W - PAD_L - PAD_R);
  const y = (v: number) => PAD_T + (1 - (v - vMin) / spanV) * (H - PAD_T - PAD_B);

  const path = stepPath(points, x, y);
  const last = points[points.length - 1] as TrajectoryPoint;
  const area = `${path} L${x(tMax).toFixed(1)},${y(vMin).toFixed(1)} L${x(tMin).toFixed(1)},${y(vMin).toFixed(1)} Z`;
  const ticks = [vMin, vMin + spanV / 2, vMax];

  const shown = values.map((value) => num(value, digits));
  const flatShown = points.length > 1 && shown.every((text) => text === shown[0]);
  const spread = Math.max(...values) - Math.min(...values);
  const flatExactly = points.length > 1 && spread === 0;

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="chart__svg">
        {ticks.map((tick, index) => (
          <g key={`g-${index}-${tick}`}>
            <line className="chart__grid" x1={PAD_L} x2={W - PAD_R} y1={y(tick)} y2={y(tick)} />
            <text className="chart__tick" x={PAD_L - 8} y={y(tick) + 4} textAnchor="end">
              {num(tick, 1)}
            </text>
          </g>
        ))}
        {limit === null ? null : (
          <>
            <line className="chart__limit" x1={PAD_L} x2={W - PAD_R} y1={y(limit)} y2={y(limit)} />
            <text className="chart__limit-text" x={W - PAD_R} y={y(limit) - 7} textAnchor="end">
              предел {num(limit, 2)} {unit}
            </text>
          </>
        )}
        <path className="chart__area" d={area} />
        <path className="chart__line" d={path} pathLength={1} />
        {points.map((p, index) => (
          <circle key={`d-${index}-${p.time}-${p.value}`} className="chart__dot" cx={x(p.time)} cy={y(p.value)} r={3.5} />
        ))}
        {points.map((p, index) => (
          <text key={`t-${index}-${p.time}`} className="chart__tick" x={x(p.time)} y={H - 12} textAnchor="middle">
            {num(p.time, 1)}
          </text>
        ))}
      </svg>
      <figcaption className="chart__caption">
        {label}, {unit}; по горизонтали — часы от момента решения. Считано {points.length} точек с шагом{" "}
        {num(spanT / Math.max(points.length - 1, 1), 2)} ч. Линия идёт ступенями намеренно: между соседними
        точками расчёта промежуточных значений никто не считал, и наклонный отрезок утверждал бы их. Ступень
        держит последнее посчитанное значение до следующей точки и ничего не додумывает; на деле переход
        между точками не мгновенный — отклик гидроочистки объявлен с запаздыванием, и его форму этот расчёт
        не описывает.
      </figcaption>
      {flatShown ? (
        <p className="chart__degenerate">
          {flatExactly
            ? `За горизонт значение не меняется: во всех ${points.length} точках ровно ${shown[0]} ${unit}. Плоская линия — это результат расчёта, а не ошибка отрисовки.`
            : `За горизонт значение не меняется на показанной точности: во всех ${points.length} точках ${shown[0]} ${unit}. Полный разброс между ними — ${num(spread, digits + 4)} ${unit}: он есть, но лежит за пределом отображаемых знаков. Плоская линия — это результат расчёта, а не ошибка отрисовки; шкала не растянута, чтобы этот разброс не выглядел значимым.`}
          {" "}
          Последняя точка — {num(last.time, 1)} ч.
        </p>
      ) : null}
    </figure>
  );
}
