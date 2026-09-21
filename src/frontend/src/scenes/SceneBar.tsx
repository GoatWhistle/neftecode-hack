import type { PresetKey } from "../run/presets";
import { PRESETS, PRESET_ORDER } from "../run/presets";
import "../styles/whatif.css";

interface Props {
  active: PresetKey | null;
  loading: boolean;
  running: boolean;
  ready: boolean;
  done: boolean;
  error: string | null;
  onPreset: (key: PresetKey) => void;
  onStart: () => void;
  onAdvanced: () => void;
  children?: React.ReactNode;
}

export function SceneBar({ active, loading, running, ready, done, error, onPreset, onStart, onAdvanced, children }: Props) {
  return (
    <section className="scenes" aria-labelledby="scenes-title">
      <div className="scenes__head">
        <h2 className="scenes__title" id="scenes-title">Запустить советчика</h2>
        <button type="button" className="scenes__advanced" onClick={onAdvanced}>Расширенные условия</button>
      </div>
      <div className="scenes__grid" role="group" aria-label="Готовые сцены">
        {PRESET_ORDER.map((key) => {
          const item = PRESETS[key];
          return (
            <button key={key} type="button" className={`scenes__card${active === key ? " is-active" : ""}`}
              aria-pressed={active === key} disabled={running || loading} onClick={() => onPreset(key)}>
              <span className="scenes__label">{item.label}</span>
              <strong className="scenes__name">{item.title}</strong>
              <small className="scenes__note">{item.note}</small>
            </button>
          );
        })}
      </div>
      <div className="scenes__actions">
        <button type="button" className="scenes__start" disabled={running || loading || !ready} onClick={onStart}>
          {loading ? "Загружаю условия…" : done ? "Запустить ещё раз" : "Запустить расчёт"}
        </button>
        {children}
      </div>
      {error ? <p className="scenes__error" role="alert">{error}</p> : null}
    </section>
  );
}
