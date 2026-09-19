import { useCallback, useState } from "react";
import type { Conditions, RunOptions } from "./options";
import { FAULT_LABELS } from "./options";
import type { RunStatus } from "./types";
import { NumberField, TankField } from "./ConfigFields";
import { ConfigBrief } from "./ConfigBrief";
import { Select } from "../ui/Select";

export interface ConfigStageProps {
  options: RunOptions | null;
  conditions: Conditions;
  status: RunStatus;
  error: string | null;
  onChange: (patch: Partial<Conditions>) => void;
  onScenario: (name: string) => void;
  onStart: () => void;
  onReset: () => void;
  onRetry?: () => Promise<boolean>;
  pending?: boolean;
}

export function ConfigStage({
  options,
  conditions,
  status,
  error,
  onChange,
  onScenario,
  onStart,
  onReset,
  onRetry,
  pending
}: ConfigStageProps) {
  const [retrying, setRetrying] = useState(false);
  const [retryFailed, setRetryFailed] = useState(false);
  const retry = useCallback(() => {
    if (!onRetry) return;
    setRetrying(true);
    setRetryFailed(false);
    void onRetry().then((ok) => {
      setRetrying(false);
      setRetryFailed(!ok);
    });
  }, [onRetry]);

  const running = status === "running";
  const waiting = running && pending === true;
  const label = waiting
    ? "Запускаю…"
    : running
      ? "Идёт расчёт…"
      : status === "idle"
        ? "Запустить"
        : "Запустить заново";
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
        <div className="config__offline">
          <p className="config__offline-text">
            Условия прогона от сервера не получены: живой прогон возможен только из{" "}
            <code>neftecode serve</code>.
          </p>
          {onRetry ? (
            <p className="config__offline-actions">
              <button type="button" className="config__ghost" disabled={retrying} onClick={retry}>
                {retrying ? "Повторяю запрос…" : "Повторить запрос условий"}
              </button>
              {retryFailed ? (
                <span className="config__offline-again" role="status">
                  Сервер условий снова не ответил.
                </span>
              ) : null}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="config__body">
          <div className="config__groups">
            <fieldset className="config__group" disabled={running}>
              <legend className="config__legend">Какой прогон</legend>
              <div className="config__grid">
                <Select label="Сценарий" value={conditions.scenario} disabled={running}
                  onChange={onScenario}
                  options={options.scenarios.map((name) => ({ value: name, label: name }))} />

                <Select label="Момент решения" value={conditions.snapshot} disabled={running}
                  onChange={(value) => onChange({ snapshot: value })}
                  options={options.snapshots.map((item) => ({ value: item.key, label: item.title }))} />

                <Select label="Отказ источника" value={conditions.fault} disabled={running}
                  onChange={(value) => onChange({ fault: value })}
                  options={options.faults.map((name) => ({
                    value: name,
                    label: FAULT_LABELS[name] ?? name
                  }))} />

                <NumberField label="Производительность" unit="т/ч" step="1"
                  value={conditions.throughput_tph} disabled={running}
                  onChange={(value) => onChange({ throughput_tph: value })} />
              </div>
            </fieldset>

            <fieldset className="config__group" disabled={running}>
              <legend className="config__legend">Пределы продукта</legend>
              <div className="config__grid">
                <NumberField label="Сера сырья" unit="% масс." step="0.01"
                  value={conditions.crude_sulfur_wt_pct} disabled={running}
                  onChange={(value) => onChange({ crude_sulfur_wt_pct: value })} />
                <NumberField label="Предел серы продукта" unit="мг/кг" step="0.5"
                  value={conditions.product_sulfur_mgkg} disabled={running}
                  onChange={(value) => onChange({ product_sulfur_mgkg: value })} />
                <NumberField label="Предел T95" unit="°C" step="1"
                  value={conditions.product_t95_c} disabled={running}
                  onChange={(value) => onChange({ product_t95_c: value })} />
                <NumberField label="Минимум цетанового числа" step="0.5"
                  value={conditions.product_cetane_number} disabled={running}
                  onChange={(value) => onChange({ product_cetane_number: value })} />
              </div>
            </fieldset>

            {options.defaults.tanks.length > 0 ? (
              <fieldset className="config__group" disabled={running}>
                <legend className="config__legend">Резервуар</legend>
                <div className="config__grid">
                  <TankField conditions={conditions} tanks={options.defaults.tanks} tank={tank}
                    disabled={running} onChange={onChange} />
                </div>
              </fieldset>
            ) : null}
          </div>

          <ConfigBrief options={options} conditions={conditions} tank={tank} />
        </div>
      )}

      <div className="config__actions">
        <button
          type="button"
          className={`config__start ${waiting ? "config__start--waiting" : ""}`}
          disabled={running || options === null}
          onClick={onStart}
        >
          {label}
        </button>
        {status !== "idle" ? (
          <button
            type="button"
            className="config__ghost config__ghost--enter"
            title={running ? "То же самое делает клавиша Escape" : undefined}
            onClick={onReset}
          >
            {running ? "Остановить прогон" : "Убрать результат"}
          </button>
        ) : null}
        {running ? (
          <span className="config__shortcut">
            или клавиша <kbd className="config__key">Esc</kbd>
          </span>
        ) : null}
      </div>

      {error ? (
        <p className="config__error" role="alert">{error}</p>
      ) : null}
    </section>
  );
}
