import { useId, useState } from "react";
import { EpisodeList } from "./EpisodeList";
import { HistoryMoment } from "./HistoryMoment";
import { HistoryPeriod } from "./HistoryPeriod";
import type { HistoryCatalog, HistorySelection, HistoryOverview } from "./types";
import "./history.css";

export { localTime } from "./moment";

interface Props {
  id?: string;
  catalog: HistoryCatalog | null;
  selection: HistorySelection | null;
  /** Срез в условиях следующего запуска: с него открывается предпросмотр. */
  current?: string | null;
  onSelect: (selection: HistorySelection) => void;
  onMore?: (offset: number) => void;
  overview?: HistoryOverview | null;
  onOverview?: (start: string, end: string) => void;
  onExclusionsMore?: (offset: number) => void;
  disabled?: boolean;
  error?: string | null;
}

type Mode = "episodes" | "exact" | "period";

const MODES: { key: Mode; label: string }[] = [
  { key: "episodes", label: "Готовые эпизоды" },
  { key: "exact", label: "Точная дата" },
  { key: "period", label: "Обзор периода" }
];

/** Общий выбор данных для расчёта: сначала режим, затем инструменты этого режима. */
export function HistoryExplorer({ id, catalog, selection, current, onSelect, onMore, disabled, error, overview, onOverview, onExclusionsMore }: Props) {
  const [mode, setMode] = useState<Mode>("episodes");
  const base = useId();
  const locked = disabled ?? false;
  const unavailable = catalog && !catalog.arbitrary.available
    ? <p className="history__hint">Доступны только готовые эпизоды. {catalog.arbitrary.reason}</p> : null;
  const coverage = catalog?.arbitrary.available ? catalog.coverage ?? null : null;

  return <section id={id} className="history" aria-label="Выбор данных для расчёта">
    <div className="history__tabs" role="tablist" aria-label="Способ выбора">
      {MODES.map((item) => <button key={item.key} type="button" role="tab" id={`${base}-${item.key}`}
        aria-selected={mode === item.key} aria-controls={`${base}-panel`} tabIndex={mode === item.key ? 0 : -1}
        className="history__tab" onClick={() => setMode(item.key)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
          const at = MODES.findIndex((entry) => entry.key === mode);
          const next = MODES[(at + (event.key === "ArrowRight" ? 1 : MODES.length - 1)) % MODES.length]!;
          setMode(next.key);
          document.getElementById(`${base}-${next.key}`)?.focus();
        }}>{item.label}</button>)}
    </div>
    <div className="history__panel" role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-${mode}`}>
      {error && <p className="history__error" role="alert">{error}</p>}
      {!catalog ? <p role="status">Каталог ещё не получен.</p>
        : mode === "episodes" ? <EpisodeList catalog={catalog} selection={selection} current={current ?? null}
            onUse={onSelect} onMore={onMore} disabled={locked} />
        : !coverage ? unavailable
        : mode === "exact" ? <HistoryMoment coverage={coverage} gridMinutes={catalog.grid_minutes}
            onSelect={onSelect} disabled={locked} />
        : onOverview ? <HistoryPeriod coverage={coverage} overview={overview ?? null} onOverview={onOverview}
            onExclusionsMore={onExclusionsMore} disabled={locked} />
        : <p className="history__hint">Обзор периода недоступен.</p>}
      {mode === "episodes" && catalog && <p className="history__hint">Выбор меняет условия следующего запуска; расчёт
        запускается основной кнопкой. Название эпизода — описание исторического периода, а не обещание результата.</p>}
    </div>
  </section>;
}
