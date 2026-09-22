import { useMemo, useState } from "react";
import type { ConsequenceEvent, ConsequenceSeries, ScreenPayload } from "../../types";
import { Empty } from "../../ui/Primitives";
import { num } from "../../format";
import { axisOf, scale } from "../../compare/tradeoffView";
import {
  applicabilityMoments, defaultSeries, directionWord, eventLabel, originWord, segments, worstStatus
} from "./model";
import "../../styles/consequences.css";

export interface ConsequencesProps {
  payload: ScreenPayload;
}

const W = 640;
const H = 260;
const PAD = { left: 60, right: 20, top: 16, bottom: 36 };

function statusWord(status: "pass" | "fail" | "unknown"): string {
  // «нет оценки» относится и к пустому ряду: ничего не проверено — не значит «в пределе».
  if (status === "fail") return "нарушение";
  if (status === "unknown") return "нет оценки";
  return "в пределе";
}

function Chart({ series, horizonHours, events }: {
  series: ConsequenceSeries; horizonHours: number; events: ConsequenceEvent[];
}) {
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
      {events.map((e, i) => {
        const marks = [{ t: e.t, cls: "action", label: `Д${i + 1}` }];
        if (e.response_t !== e.t) marks.push({ t: e.response_t, cls: "response", label: `О${i + 1}` });
        return marks.filter((m) => m.t >= 0 && m.t <= xAxis.max + 1e-9).map((m) => (
          <g key={`${m.cls}-${i}`} className={`cns__event cns__event--${m.cls}`}>
            <line x1={px(m.t)} x2={px(m.t)} y1={PAD.top} y2={PAD.top + ih} />
            <text x={px(m.t) + 3} y={PAD.top + 11}>{m.label}</text>
          </g>
        ));
      })}
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

function EventList({ events, missing, note }: {
  events: ConsequenceEvent[]; missing: boolean; note?: string | undefined;
}) {
  if (missing) {
    return <p className="cns__hint">Моменты действий и отклика в этой записи не сохранены — на графике не показаны.</p>;
  }
  if (events.length === 0) {
    return <p className="cns__hint">Выбранный план не меняет режим на горизонте: отметок действий нет.</p>;
  }
  return (
    <div className="cns__events">
      <table className="cns__table">
        <caption>Действия выбранного плана (Д) и объявленный отклик (О)</caption>
        <thead>
          <tr>
            <th scope="col">№</th>
            <th scope="col">Что</th>
            <th scope="col">Действие</th>
            <th scope="col">Отклик</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e, i) => (
            <tr key={i}>
              <th scope="row">Д{i + 1}</th>
              <td>{eventLabel(e)} <span className="cns__muted">({originWord(e.origin)})</span></td>
              <td>{num(e.t, 1)} ч</td>
              <td>
                {e.kind === "control"
                  ? <>О{i + 1}: {num(e.response_t, 1)} ч (запаздывание {num(e.lag_hours, 1)} ч, {e.lag_source})</>
                  : <>со своего шага (модель смешения)</>}
                {e.partial_response
                  ? <> · до {num(e.partial_response.until_hours, 1)} ч действует доля хода {num(e.partial_response.share, 2)}</>
                  : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {note ? <p className="cns__note">{note}</p> : null}
    </div>
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

  const selectedRegion = applicabilityMoments(consequences.applicability.selected);
  const holdRegion = consequences.applicability.hold ? applicabilityMoments(consequences.applicability.hold) : null;
  const eventsMissing = !consequences.events || consequences.events.selected == null;
  const events = consequences.events?.selected ?? [];
  const hours = (list: number[]) => list.map((t) => `${num(t, 1)} ч`).join(", ");

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
              {worst !== "pass" ? <span className="cns__tab-state"> · {statusWord(worst)}</span> : null}
            </button>
          );
        })}
      </div>

      <div className="cns__figure">
        <Chart series={current} horizonHours={consequences.horizon_hours} events={events} />
        <figcaption className="cns__legend">
          <span><i className="cns__key cns__key--selected" /> выбранный план</span>
          {current.candidates.hold ? <span><i className="cns__key cns__key--hold" /> сохранить режим</span> : null}
          <span><i className="cns__key cns__key--limit" /> предел ({current.limit.source ?? "источник не передан"})</span>
          {events.length > 0 ? <span><i className="cns__key cns__key--action" /> Д — действие, О — отклик</span> : null}
        </figcaption>
      </div>

      {!consequences.hold.available ? (
        <p className="cns__blocked">
          Сравнение с сохранением режима недоступно: {consequences.hold.reason ?? "расчёт не выполнен"}.
        </p>
      ) : consequences.hold.source === "recomputed_same_evaluator" ? (
        <p className="cns__hint">
          Сохранение режима не входило в исследованный пул — рассчитано тем же расчётом на тех же входах.
        </p>
      ) : null}

      {selectedRegion.outside.length > 0 ? (
        <p className="cns__warn">
          Выбранный план: модель отклика вне откалиброванной области на {hours(selectedRegion.outside)} —
          числа на этих моментах — экстраполяция.
        </p>
      ) : null}
      {selectedRegion.unknown.length > 0 ? (
        <p className="cns__warn">
          Выбранный план: применимость модели не установлена на {hours(selectedRegion.unknown)}.
        </p>
      ) : null}
      {holdRegion && holdRegion.outside.length > 0 ? (
        <p className="cns__warn">
          Сохранить режим: вне откалиброванной области на {hours(holdRegion.outside)} — экстраполяция.
        </p>
      ) : null}
      {holdRegion && holdRegion.unknown.length > 0 ? (
        <p className="cns__warn">
          Сохранить режим: применимость модели не установлена на {hours(holdRegion.unknown)}.
        </p>
      ) : null}

      <EventList events={events} missing={eventsMissing} note={consequences.events_note} />

      <ValueTable series={current} />

      <p className="cns__note">{consequences.note}</p>
    </div>
  );
}
