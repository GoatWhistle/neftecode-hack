import { useState } from "react";
import type { HistoryOverview } from "./types";
import { canonical, coverageMin } from "./HistoryMoment";
import { HistoryOverviewPanel } from "./HistoryOverviewPanel";

interface Props {
  coverage: { start: string; end: string; model_valid_from: string };
  overview: HistoryOverview | null;
  onOverview: (start: string, end: string) => void;
  onExclusionsMore: ((offset: number) => void) | undefined;
  disabled: boolean;
}

/** Обзор периода — исследовательский режим: наблюдения без прогноза и решения. */
export function HistoryPeriod({ coverage, overview, onOverview, onExclusionsMore, disabled }: Props) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const min = coverageMin(coverage);
  const valid = start !== "" && end !== "" && canonical(start) >= min && canonical(end) <= coverage.end
    && canonical(start) <= canonical(end);
  return <div className="history__period">
    <p className="history__lead">Просмотр данных без расчёта рекомендации.</p>
    <div className="history__exact-row">
      <label>Начало периода<input type="datetime-local" min={min} max={coverage.end} value={start}
        onChange={(event) => setStart(event.target.value)} /></label>
      <label>Конец периода<input type="datetime-local" min={min} max={coverage.end} value={end}
        onChange={(event) => setEnd(event.target.value)} /></label>
      <button type="button" className="history__primary" disabled={disabled || !valid}
        onClick={() => onOverview(start, end)}>Показать наблюдения</button>
    </div>
    <p className="history__hint">До 48 точек за запрос; прогноз и решение для точек обзора не вычисляются.</p>
    {overview && <HistoryOverviewPanel overview={overview} onMore={onExclusionsMore} disabled={disabled} />}
  </div>;
}
