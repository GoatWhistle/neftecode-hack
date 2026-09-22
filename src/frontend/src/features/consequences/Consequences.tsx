import { useMemo, useState } from "react";
import type { ConsequenceSeries, ScreenPayload } from "../../types";
import { Empty } from "../../ui/Primitives";
import { num } from "../../format";
import { axisOf, scale } from "../../compare/tradeoffView";
import { defaultSeries, directionWord, outOfRegionMoments, segments, worstStatus } from "./model";
import "../../styles/consequences.css";

export interface ConsequencesProps {
  payload: ScreenPayload;
}

const W = 640;
const H = 260;
const PAD = { left: 60, right: 20, top: 16, bottom: 36 };

function statusWord(status: "pass" | "fail" | "unknown"): string {
  if (status === "fail") return "нарушение";
  if (status === "unknown") return "нет оценки";
  return "в пределе";
}

function Chart({ series, horizonHours }: { series: ConsequenceSeries; horizonHours: number }) {
  const selected = series.candidates.selected;
  const hold = series.candidates.hold;
  const allValues = [
    ...selected.points.map((p) => p.value),
    ...(hold ? hold.points.map((p) => p.value) : []),
    series.limit.value
  ].filter((v): v is number => v !== null);
  const yAxis = useMemo(() => axisOf(allValues), [allValues]);
  const xAxis = { min: 0, max: horizonHours || 1, degenerate: horizonHours <= 0 };
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const px = (t: number) => PAD.left + scale(t, xAxis, iw);
  const py = (v: number) => PAD.top + scale(v, yAxis, ih, true);

  const path = (points: { t: number; value: number | null; status: string }[]) =>
    segments(points as never)
      .map((segment) => segment.points.map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.t)} ${py(p.value as number)}`).join(" "))
      .join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" className="cns__svg"
      aria-label={`График ${series.quality}: время по горизонтали, значение по вертикали`}>
      <rect x={PAD.left} y={PAD.top} width={iw} height={ih} className="cns__plot" />
      {[0, 0.5, 1].map((frac) => (
        <text key={frac} x={PAD.left - 6} y={PAD.top + (1 - frac) * ih + 4} textAnchor="end" className="cns__tick">
          {num(yAxis.min + (yAxis.max - yAxis.min) * frac, 2)}
        </text>
      ))}
      {[0, 0.5, 1].map((frac) => (
        <text key={frac} x={PAD.left + frac * iw} y={PAD.top + ih + 16}
          textAnchor={frac === 0 ? "start" : frac === 1 ? "end" : "middle"} className="cns__tick">
          {num(xAxis.min + (xAxis.max - xAxis.min) * frac, 1)} ч
        </text>
      ))}
      {series.limit.value !== null ? (
        <>
          <line x1={PAD.left} x2={PAD.left + iw} y1={py(series.limit.value)} y2={py(series.limit.value)}
            className="cns__limit" />
          <text x={PAD.left + iw} y={py(series.limit.value) - 4} textAnchor="end" className="cns__limit-label">
            предел {directionWord(series.direction)} {num(series.limit.value, 2)}
          </text>
        </>
      ) : null}
      {hold ? <path d={path(hold.points)} className="cns__line cns__line--hold" /> : null}
      <path d={path(selected.points)} className="cns__line cns__line--selected" />
      {selected.points.filter((p) => p.value !== null).map((p) => (
        <circle key={`sel-${p.t}`} cx={px(p.t)} cy={py(p.value as number)} r={4}
          className={`cns__pt cns__pt--${p.status}`} />
      ))}
      {hold ? hold.points.filter((p) => p.value !== null).map((p) => (
        <rect key={`hold-${p.t}`} x={px(p.t) - 3} y={py(p.value as number) - 3} width={6} height={6}
          className={`cns__pt cns__pt--hold cns__pt--${p.status}`} />
      )) : null}
    </svg>
  );
}

function ValueTable({ series }: { series: ConsequenceSeries }) {
  const times = Array.from(new Set([
    ...series.candidates.selected.points.map((p) => p.t),
    ...(series.candidates.hold?.points.map((p) => p.t) ?? [])
  ])).sort((a, b) => a - b);
  const byT = (points: { t: number; value: number | null; status: string }[], t: number) =>
    points.find((p) => Math.abs(p.t - t) < 1e-9) ?? null;
  return (
    <table className="cns__table">
      <caption>Значения по моментам (то же, что на графике)</caption>
      <thead>
        <tr>
          <th scope="col">Момент</th>
          <th scope="col">Выбранный план</th>
          <th scope="col">Сохранить режим</th>
        </tr>
      </thead>
      <tbody>
        {times.map((t) => {
          const s = byT(series.candidates.selected.points, t);
          const h = series.candidates.hold ? byT(series.candidates.hold.points, t) : null;
          return (
            <tr key={t}>
              <th scope="row">{num(t, 1)} ч</th>
              <td className={s ? `cns__cell cns__cell--${s.status}` : "cns__cell"}>
                {s && s.value !== null ? `${num(s.value, 3)} (${statusWord(s.status as never)})` : "нет числа"}
              </td>
              <td className={h ? `cns__cell cns__cell--${h.status}` : "cns__cell"}>
                {series.candidates.hold
                  ? (h && h.value !== null ? `${num(h.value, 3)} (${statusWord(h.status as never)})` : "нет числа")
                  : "не посчитан"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Consequences({ payload }: ConsequencesProps) {
  const hasField = Object.prototype.hasOwnProperty.call(payload.decision, "consequences");
  const consequences = payload.decision.consequences;
  const [active, setActive] = useState<string | null>(null);

  if (!hasField) {
    return (
      <Empty>
        Траектория не сохранена: запись сделана до появления этого показателя. Числа последствий
        для этого прогона недоступны.
      </Empty>
    );
  }
  if (!consequences) {
    return <Empty>Последствия во времени не считались: решение не выдано.</Empty>;
  }

  const current = consequences.series.find((s) => s.limit_id === active) ?? defaultSeries(consequences);
  if (!current) return <Empty>Проверяемых показателей качества в результате нет.</Empty>;

  const applicability = consequences.applicability.selected;
  const outOfRegion = outOfRegionMoments(applicability);

  return (
    <div className="cns">
      <p className="cns__lead">
        Горизонт решения {num(consequences.horizon_hours, 1)} ч, расчётный шаг {num(consequences.step_hours, 2)} ч.
        Значения — точки, уже проверенные Gate; переключение показателя не считает заново и не
        вызывает модель.
      </p>
      <div className="cns__tabs" role="tablist" aria-label="Показатель качества">
        {consequences.series.map((s) => {
          const worst = worstStatus(s.candidates.selected.points);
          return (
            <button key={s.limit_id} type="button" role="tab" aria-selected={s.limit_id === current.limit_id}
              className={`cns__tab cns__tab--${worst} ${s.limit_id === current.limit_id ? "is-active" : ""}`}
              onClick={() => setActive(s.limit_id)}>
              {s.quality}{s.unit ? ` (${s.unit})` : ""}
            </button>
          );
        })}
      </div>

      <div className="cns__figure">
        <Chart series={current} horizonHours={consequences.horizon_hours} />
        <figcaption className="cns__legend">
          <span><i className="cns__key cns__key--selected" /> выбранный план</span>
          {current.candidates.hold ? <span><i className="cns__key cns__key--hold" /> сохранить режим</span> : null}
          <span><i className="cns__key cns__key--limit" /> предел ({current.limit.source ?? "источник не передан"})</span>
        </figcaption>
      </div>

      {!consequences.hold.available ? (
        <p className="cns__blocked">
          Сравнение с hold недоступно: {consequences.hold.reason ?? "расчёт hold не выполнен"}.
        </p>
      ) : consequences.hold.source === "recomputed_same_evaluator" ? (
        <p className="cns__hint">
          Hold не входил в исследованный пул — пересчитан тем же evaluator на тех же входах отдельно.
        </p>
      ) : null}

      {outOfRegion.length > 0 ? (
        <p className="cns__warn">
          Модель отклика вне откалиброванной области на {outOfRegion.map((t) => `${num(t, 1)} ч`).join(", ")}:
          числа на этих моментах — экстраполяция.
        </p>
      ) : null}

      <ValueTable series={current} />

      <p className="cns__note">{consequences.note}</p>
    </div>
  );
}
