import { num } from "../../format";
import type { TankParkStatus, TankParkTrajectory } from "../../types";

const STATUS: Record<TankParkStatus, string> = {
  available: "свободен",
  filling: "налив",
  awaiting_passport: "паспорт",
  ready: "готов",
  draining: "слив"
};

function pct(mass: number, capacity: number): string {
  return capacity > 0 ? `${num(100 * mass / capacity, 0)}%` : "—";
}

function property(value: number | null, unit: string): string {
  return value === null ? "неизвестно" : `${num(value, 2)} ${unit}`;
}

export function TankPark({ park }: { park: TankParkTrajectory }) {
  const ids = park.frames[0]?.state.tanks.map((tank) => tank.tank_id) ?? [];
  const limiting = park.frames.flatMap((frame) => frame.reasons.map((reason) => ({ time: frame.time_h, reason })));
  return (
    <section className="tank-park" aria-labelledby="tank-park-title">
      <div className="tank-park__head">
        <div>
          <h3 id="tank-park-title" className="answer-part__title">Оборот резервуаров</h3>
          <p>Расписание рассчитано сервером той же моделью, которую проверяет Gate.</p>
        </div>
        <span className={`tank-park__verdict tank-park__verdict--${park.feasible ? "pass" : "fail"}`}>
          {park.feasible ? "баланс соблюдён" : "есть ограничение"}
        </span>
      </div>
      <div className="tank-park__times" aria-hidden="true">
        <span>резервуар</span>
        <span>время {num(park.frames[0]?.time_h ?? 0, 1)}—{num(park.frames.at(-1)?.time_h ?? 0, 1)} ч</span>
        <span>остаток</span>
      </div>
      <div className="tank-park__list">
        {ids.map((id) => {
          const states = park.frames.map((frame) => frame.state.tanks.find((tank) => tank.tank_id === id)!);
          const terminal = states.at(-1)!;
          const events = park.frames.filter((frame) =>
            (frame.inflow_by_tank[id] ?? 0) > 0 || (frame.outflow_by_tank[id] ?? 0) > 0 || frame.reasons.length > 0);
          return (
            <details className="tank-park__tank" key={id}>
              <summary>
                <span className="tank-park__name">{id}</span>
                <span className="tank-park__strip">
                  {states.map((tank, index) => (
                    <span className={`tank-park__cell tank-park__cell--${tank.status}`} key={`${id}-${index}`}
                      title={`${park.frames[index]?.time_h ?? 0} ч · ${STATUS[tank.status]} · ${num(tank.mass_t, 1)} т`}>
                      <span className="tank-park__cell-time">{num(park.frames[index]?.time_h ?? 0, 1)} ч</span>
                      <span className="tank-park__cell-status">{STATUS[tank.status]}</span>
                    </span>
                  ))}
                </span>
                <span className="tank-park__mass">{num(terminal.mass_t, 0)} т · {pct(terminal.mass_t, terminal.capacity_t)}</span>
              </summary>
              <div className="tank-park__detail">
                <dl>
                  <div><dt>Партия</dt><dd>{terminal.batch_id ?? "нет"}</dd></div>
                  <div><dt>Источник состояния</dt><dd>{terminal.provenance}</dd></div>
                  <div><dt>Предел слива</dt><dd>{num(terminal.nominal_drain_tph, 1)} т/ч</dd></div>
                  <div><dt>Сера</dt><dd>{property(terminal.properties.sulfur_mgkg ?? null, "мг/кг")}</dd></div>
                  <div><dt>T95</dt><dd>{property(terminal.properties.t95_c ?? null, "°C")}</dd></div>
                </dl>
                {events.length > 0 ? (
                  <ul>{events.map((frame) => (
                    <li key={`${id}-${frame.time_h}`}>
                      {num(frame.time_h, 1)} ч: вход {num(frame.inflow_by_tank[id] ?? 0, 1)} т,
                      выход {num(frame.outflow_by_tank[id] ?? 0, 1)} т
                      {frame.reasons.length ? ` · ${frame.reasons.join("; ")}` : ""}
                    </li>
                  ))}</ul>
                ) : <p>На горизонте операций массы нет.</p>}
              </div>
            </details>
          );
        })}
      </div>
      <p className="tank-park__balance">
        Вход {num(park.terminal.total_in_t, 1)} т · выход {num(park.terminal.total_out_t, 1)} т ·
        остаток {num(park.terminal.mass_t, 1)} т · ошибка баланса {num(park.terminal.balance_error_t, 6)} т
      </p>
      {limiting.length > 0 ? (
        <div className="tank-park__limit" role="alert">
          <strong>Ограничившее событие:</strong> {num(limiting[0]!.time, 1)} ч · {limiting[0]!.reason}
        </div>
      ) : null}
      <p className="tank-park__note">{park.model_version}. Четыре резервуара и начальные фазы — параметры сценария, не измеренная конфигурация завода.</p>
    </section>
  );
}
