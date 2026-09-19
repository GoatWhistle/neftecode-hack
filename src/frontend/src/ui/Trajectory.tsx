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
}

const W = 720;
const H = 240;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 34;

export function Trajectory({ points, limit, unit, label }: TrajectoryProps) {
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

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = `${path} L${x(tMax).toFixed(1)},${y(vMin).toFixed(1)} L${x(tMin).toFixed(1)},${y(vMin).toFixed(1)} Z`;
  const ticks = [vMin, vMin + spanV / 2, vMax];

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="chart__svg">
        {ticks.map((tick) => (
          <g key={tick}>
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
        {points.map((p) => (
          <circle key={`${p.time}-${p.value}`} className="chart__dot" cx={x(p.time)} cy={y(p.value)} r={3.5} />
        ))}
        {points.map((p) => (
          <text key={`t-${p.time}`} className="chart__tick" x={x(p.time)} y={H - 12} textAnchor="middle">
            {num(p.time, 1)}
          </text>
        ))}
      </svg>
      <figcaption className="chart__caption">
        {label}, {unit}; по горизонтали — часы от момента решения
      </figcaption>
    </figure>
  );
}
