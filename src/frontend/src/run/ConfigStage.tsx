import type { Conditions, RunOptions } from "./options";
import { FAULT_LABELS } from "./options";
import type { RunStatus } from "./types";
import { NumberField, TankField } from "./ConfigFields";

export interface ConfigStageProps {
  options: RunOptions | null;
  conditions: Conditions;
  status: RunStatus;
  error: string | null;
  onChange: (patch: Partial<Conditions>) => void;
  onScenario: (name: string) => void;
  onStart: () => void;
  onReset: () => void;
}

export function ConfigStage({
  options,
  conditions,
  status,
  error,
  onChange,
  onScenario,
  onStart,
  onReset
}: ConfigStageProps) {
  const running = status === "running";
  const tank = options?.defaults.tanks.find((item) => item.id === conditions.tank) ?? null;

  return (
    <section id="config" className="config">
      <header className="config__head">
        <span className="config__step">0</span>
        <h2 className="config__title">Условия прогона</h2>
        <p className="config__lead">
          Соберите условия и запустите расчёт. Остальные восемь этапов появятся по мере того, как сервер
          их отдаст: пока запуска не было, показывать там нечего.
        </p>
      </header>

      {options === null ? (
        <p className="config__offline">
          Сервер условий недоступен: живой прогон возможен только из <code>neftecode serve</code>.
        </p>
      ) : (
        <div className="config__grid">
          <label className="config__field">
            <span>Сценарий</span>
            <select value={conditions.scenario} disabled={running}
              onChange={(event) => onScenario(event.target.value)}>
              {options.scenarios.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>

          <label className="config__field">
            <span>Момент решения</span>
            <select value={conditions.snapshot} disabled={running}
              onChange={(event) => onChange({ snapshot: event.target.value })}>
              {options.snapshots.map((item) => (
                <option key={item.key} value={item.key}>{item.title}</option>
              ))}
            </select>
          </label>

          <label className="config__field">
            <span>Отказ источника</span>
            <select value={conditions.fault} disabled={running}
              onChange={(event) => onChange({ fault: event.target.value })}>
              {options.faults.map((name) => (
                <option key={name} value={name}>{FAULT_LABELS[name] ?? name}</option>
              ))}
            </select>
          </label>

          <NumberField label="Сера сырья, % масс." step="0.01" value={conditions.crude_sulfur_wt_pct}
            disabled={running} onChange={(value) => onChange({ crude_sulfur_wt_pct: value })} />
          <NumberField label="Предел серы продукта, мг/кг" step="0.5" value={conditions.product_sulfur_mgkg}
            disabled={running} onChange={(value) => onChange({ product_sulfur_mgkg: value })} />
          <NumberField label="Предел T95, °C" step="1" value={conditions.product_t95_c}
            disabled={running} onChange={(value) => onChange({ product_t95_c: value })} />
          <NumberField label="Минимум цетанового числа" step="0.5" value={conditions.product_cetane_number}
            disabled={running} onChange={(value) => onChange({ product_cetane_number: value })} />
          <NumberField label="Текущий выпуск, т/ч" step="1" value={conditions.throughput_tph}
            disabled={running} onChange={(value) => onChange({ throughput_tph: value })} />

          <TankField conditions={conditions} tanks={options.defaults.tanks} tank={tank}
            disabled={running} onChange={onChange} />
        </div>
      )}

      <div className="config__actions">
        <button type="button" className="config__start" disabled={running || options === null}
          onClick={onStart}>
          {running ? "Идёт расчёт…" : status === "idle" ? "Запустить" : "Запустить заново"}
        </button>
        {status !== "idle" && !running ? (
          <button type="button" className="config__ghost" onClick={onReset}>
            Убрать результат
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="config__error" role="alert">{error}</p>
      ) : null}
    </section>
  );
}
