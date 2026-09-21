import { useMemo, useState } from "react";
import { num, percent } from "../format";
import type { ScreenPayload, TradeoffPoint } from "../types";
import { axisOf, mapVerdict, pointStatus, scale } from "./tradeoffView";
import "../styles/tradeoff.css";

const W = 640;
const H = 300;
const PAD = { left: 64, right: 20, top: 16, bottom: 44 };

interface Props {
  payload: ScreenPayload;
}

function recipeText(point: TradeoffPoint, names: Record<string, string>): string {
  const parts = Object.entries(point.recipe).filter(([, v]) => v > 1e-9)
    .map(([key, v]) => `${names[key] ?? key} ${percent(v, 0)}`);
  return parts.length > 0 ? parts.join(", ") : "рецепт не передан";
}

export function TradeoffMapView({ payload }: Props) {
  const map = payload.decision.tradeoff ?? null;
  const [picked, setPicked] = useState<string | null>(null);
  const names = payload.explanation?.component_names ?? {};
  const points = map?.points ?? [];
  const active = points.find((p) => p.candidate_id === picked)
    ?? points.find((p) => p.selected) ?? points[0] ?? null;
  const xAxis = useMemo(() => axisOf(points.map((p) => p.cost_per_tonne)), [points]);
  const yAxis = useMemo(() => axisOf(points.map((p) => p.production_t)), [points]);
  if (!map) {
    return (
      <p className="tmap__empty">
        Карта компромиссов не строится: решение не выдано или расчёт не дошёл до сравнения допустимых планов.
      </p>
    );
  }
  const verdict = mapVerdict(map);
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const px = (p: TradeoffPoint) => PAD.left + scale(p.cost_per_tonne, xAxis, iw);
  const py = (p: TradeoffPoint) => PAD.top + scale(p.production_t, yAxis, ih, true);
  const order = [...points].sort((a, b) => Number(a.on_front) - Number(b.on_front)
    || Number(a.selected) - Number(b.selected));
  const pool = map.pool;
  const hold = map.hold;

  return (
    <div className="tmap">
      <p className={`tmap__lead tmap__lead--${verdict.kind}`}>{verdict.text}</p>
      <ul className="tmap__facts">
        <li>Допустимых вариантов в пуле: <b>{pool.admissible}</b>, сравнимо по трём осям: <b>{pool.comparable}</b></li>
        <li>Оценено кандидатов: <b>{pool.evaluated ?? "не передано"}</b>
          {pool.search_budget ? <> из бюджета поиска <b>{pool.search_budget}</b></> : null}
          {pool.rounds ? <>, раундов: <b>{pool.rounds}</b></> : null}</li>
        <li>Горизонт: <b>{map.horizon_hours === null ? "не передан" : `${num(map.horizon_hours, 1)} ч`}</b>
          {map.severity_profile ? <>, профиль тяжести: <code>{map.severity_profile}</code></> : null}</li>
        {pool.excluded_unknown_count > 0 ? (
          <li className="tmap__warn">Исключено из сравнения из-за неизвестных показателей: <b>{pool.excluded_unknown_count}</b>
            {" "}({pool.excluded_unknown.slice(0, 3).map((e) => `${e.candidate_id}: нет ${e.missing.join(", ")}`).join("; ")})</li>
        ) : null}
        {!hold.admissible ? (
          <li className="tmap__warn">Текущий режим (hold) не входит в допустимый пул{hold.note ? `: ${hold.note}` : ": он не прошёл обязательные проверки"}.</li>
        ) : null}
      </ul>
      {map.selection_note ? <p className="tmap__note">{map.selection_note}</p> : null}

      {points.length > 0 ? (
        <div className="tmap__grid">
          <figure className="tmap__figure">
            <svg viewBox={`0 0 ${W} ${H}`} role="img" className="tmap__svg"
              aria-label="График компромиссов: стоимость на тонну по горизонтали, выпуск по вертикали">
              <rect x={PAD.left} y={PAD.top} width={iw} height={ih} className="tmap__plot" />
              <text x={PAD.left + iw / 2} y={H - 6} textAnchor="middle" className="tmap__axis">Стоимость на тонну, у. е./т (меньше — лучше)</text>
              <text transform={`translate(14 ${PAD.top + ih / 2}) rotate(-90)`} textAnchor="middle" className="tmap__axis">Выпуск, т (больше — лучше)</text>
              {[0, 1].map((i) => (
                <g key={i}>
                  <text x={PAD.left + i * iw} y={PAD.top + ih + 16} textAnchor={i ? "end" : "start"} className="tmap__tick">
                    {num(xAxis.min + (xAxis.max - xAxis.min) * i, 3)}
                  </text>
                  <text x={PAD.left - 6} y={PAD.top + (1 - i) * ih + 4} textAnchor="end" className="tmap__tick">
                    {num(yAxis.min + (yAxis.max - yAxis.min) * i, 1)}
                  </text>
                </g>
              ))}
              {order.map((p) => {
                const isActive = active?.candidate_id === p.candidate_id;
                const cls = ["tmap__pt", p.on_front ? "tmap__pt--front" : "tmap__pt--dom",
                  p.selected ? "tmap__pt--sel" : "", isActive ? "tmap__pt--active" : ""].join(" ");
                const size = p.selected ? 7 : 5;
                return (
                  <g key={p.candidate_id} className={cls} tabIndex={0} role="button"
                    aria-label={`${p.candidate_id}: ${pointStatus(p)}`}
                    onClick={() => setPicked(p.candidate_id)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(p.candidate_id); } }}>
                    {p.is_hold ? <rect x={px(p) - size} y={py(p) - size} width={size * 2} height={size * 2} />
                      : <circle cx={px(p)} cy={py(p)} r={size} />}
                  </g>
                );
              })}
            </svg>
            <figcaption className="tmap__legend">
              <span><i className="tmap__key tmap__key--front" /> недоминируемый</span>
              <span><i className="tmap__key tmap__key--dom" /> доминируемый</span>
              <span><i className="tmap__key tmap__key--sel" /> выбранный ядром</span>
              <span><i className="tmap__key tmap__key--hold" /> текущий режим</span>
            </figcaption>
            {(xAxis.degenerate || yAxis.degenerate) ? (
              <p className="tmap__hint">
                {yAxis.degenerate ? "Выпуск у всех вариантов одинаков — точки лежат на одной высоте. " : ""}
                {xAxis.degenerate ? "Стоимость у всех вариантов одинакова. " : ""}
                Тяжесть режима — в карточке точки.
              </p>
            ) : null}
            {pool.points_truncated ? (
              <p className="tmap__hint">Показан весь фронт и {pool.points_shown - pool.front_distinct} из доминируемых точек по равномерной выборке; в таблице ниже те же точки. Планы с одинаковыми показателями сведены в одну точку.</p>
            ) : null}
          </figure>

          {active ? (
            <aside className="tmap__card" aria-live="polite">
              <h4 className="tmap__card-title">{active.candidate_id}{active.selected ? " · выбран ядром" : ""}</h4>
              <p className="tmap__card-status">{pointStatus(active)}</p>
              <dl className="tmap__dl">
                <dt>Выпуск</dt><dd>{num(active.production_t, 1)} т</dd>
                <dt>Стоимость</dt><dd>{num(active.cost_per_tonne, 3)} у. е./т</dd>
                <dt>Тяжесть режима</dt><dd>{num(active.severity_index, 3)}</dd>
                <dt>Изменений</dt><dd>{active.changes}</dd>
                <dt>Рецепт</dt><dd>{recipeText(active, names)}</dd>
                <dt>Производительность</dt><dd>{num(active.throughput_tph, 1)} т/ч</dd>
                <dt>Ходы уставок</dt>
                <dd>{active.moves.length === 0 ? "нет" : active.moves.map((m) => `${m.name}: ${num(m.from, 1)} → ${num(m.to, 1)}`).join("; ")}</dd>
                <dt>Проверки</dt>
                <dd>Gate пройден{active.stress_checked ? "; стресс-проверки выполнены (только для выбранного плана)" : "; стресс-проверки для этого варианта не выполнялись"}</dd>
                {active.equivalent_count > 0 ? (<><dt>Равные по показателям</dt><dd>ещё {active.equivalent_count}: {active.equivalent_ids.join(", ")}{active.equivalent_count > active.equivalent_ids.length ? "…" : ""}</dd></>) : null}
              </dl>
              {!active.selected && payload.decision.selected_plan ? (
                <p className="tmap__why">Ядро выбрало {payload.decision.selected_plan.plan_id} по действующему правилу: {map.selection_reason ?? "правило выбора не передано"}. Клик по точке только объясняет вариант и выбор не меняет.</p>
              ) : (
                <p className="tmap__why">Выбор ядра: {map.selection_reason ?? "правило не передано"}.</p>
              )}
            </aside>
          ) : null}
        </div>
      ) : null}

      {points.length > 0 ? (
        <div className="tmap__tablewrap">
          <table className="tmap__table">
            <caption>Варианты допустимого пула (то же, что на графике)</caption>
            <thead><tr><th>План</th><th>Выпуск, т</th><th>Стоимость, у. е./т</th><th>Тяжесть</th><th>Изм.</th><th>Статус</th></tr></thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.candidate_id} className={active?.candidate_id === p.candidate_id ? "is-active" : ""}>
                  <th scope="row"><button type="button" onClick={() => setPicked(p.candidate_id)}>{p.candidate_id}</button></th>
                  <td>{num(p.production_t, 1)}</td><td>{num(p.cost_per_tonne, 3)}</td><td>{num(p.severity_index, 3)}</td>
                  <td>{p.changes}</td><td>{pointStatus(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="tmap__scope">{map.scope}</p>
      <p className="tmap__scope">{map.stress_scope}</p>
    </div>
  );
}
