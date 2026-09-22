import { useState } from "react";
import { HistoryMoment } from "./HistoryMoment";
import { HistoryOverviewPanel } from "./HistoryOverviewPanel";
import type { HistoryCatalog, HistorySelection, HistoryOverview } from "./types";
import "./history.css";

interface Props {
  catalog: HistoryCatalog | null;
  selection: HistorySelection | null;
  onSelect: (selection: HistorySelection) => void;
  onMore?: (offset: number) => void;
  overview?: HistoryOverview | null;
  onOverview?: (start: string, end: string) => void;
  onExclusionsMore?: (offset: number) => void;
  disabled?: boolean;
  error?: string | null;
  recordTime?: string | null;
}

export function localTime(value: string): string {
  return value.replace("T", " ");
}

const TAG_UNITS: Record<string, string> = { "ht.T6": "°C", "ht.F9": "т/ч", "ht.F26": "м³/ч" };

function reading(value: number | null, unit: string): string {
  return value === null ? "нет измерения" : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 3 })} ${unit}`;
}

export function HistoryExplorer({ catalog, selection, onSelect, onMore, disabled, error, recordTime, overview, onOverview, onExclusionsMore }: Props) {
  const [filter, setFilter] = useState("");
  const items = catalog?.items.filter((item) => `${item.at} ${item.label}`.toLocaleLowerCase()
    .includes(filter.toLocaleLowerCase())) ?? [];
  return <section className="history" aria-label="Исторические моменты">
    <h2>Выбрать момент истории</h2>
    <p>Местное время исходных данных; часовой пояс не указан в поставке.</p>
    {recordTime && <p>Дата показанной записи: <strong>{localTime(recordTime)}</strong></p>}
    {error && <p role="alert">{error}</p>}
    {!catalog ? <p role="status">Каталог ещё не получен.</p> : <>
      <p>{catalog.note}</p>
      {catalog.snapshot_coverage && <p>Готовые срезы: {localTime(catalog.snapshot_coverage.start)} — {localTime(catalog.snapshot_coverage.end)}.
        Между срезами данные могут отсутствовать.</p>}
      {!catalog.arbitrary.available && <p>Доступны только готовые срезы. {catalog.arbitrary.reason}</p>}
      {catalog.arbitrary.available && catalog.coverage && <HistoryMoment coverage={catalog.coverage}
        disabled={disabled ?? false} onSelect={onSelect} onOverview={onOverview} />}
      {overview && <HistoryOverviewPanel overview={overview} onMore={onExclusionsMore} disabled={disabled ?? false} />}
      <label>Найти дату или название
        <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} />
      </label>
      <p>Показано {items.length} из {catalog.total}. Выбор меняет условия следующего запуска; расчёт запускается отдельно.</p>
      <ul className="history__list">
        {items.map((item) => <li key={item.snapshot}>
          <button type="button" disabled={disabled}
            aria-pressed={selection?.kind === "snapshot" && selection.snapshot === item.snapshot}
            onClick={() => onSelect({ kind: "snapshot", snapshot: item.snapshot, requested_at: item.at })}>
            <strong>{item.label}</strong><span>{localTime(item.at)}</span>
          </button>
          <p title={`ЛИМС: ${item.facts.lab_value}; ПАК: ${item.facts.pak_value}`}>ЛИМС: {reading(item.facts.lab_value, "мг/кг")} · ПАК: {reading(item.facts.pak_value, "ppm")}</p>
          {item.facts.lab_available_time && <p>ЛИМС доступен с {localTime(item.facts.lab_available_time)}</p>}
          <details><summary>Фактические признаки среза</summary>
            <p>Доля пропусков телеметрии: {item.facts.telemetry_missing_fraction === null
              ? "не передана" : `${(100 * item.facts.telemetry_missing_fraction).toFixed(1)} %`}</p>
            {Object.entries(item.measurements).map(([tag, value]) => <p key={tag}>
              {tag}: {value ? `${value.value.toLocaleString("ru-RU", { maximumFractionDigits: 3 })} ${TAG_UNITS[tag] ?? "(единица не передана)"} · ${localTime(value.time)} · возраст ${value.age_min} мин` : "нет измерения"}
            </p>)}
          </details>
          {item.synthetic_edits.length > 0 && <p>Искусственные изменения: {item.synthetic_edits.join("; ")}</p>}
        </li>)}
      </ul>
      {items.length === 0 && <p>Подходящих срезов нет.</p>}
      {catalog.next_offset !== null && onMore && <button type="button" disabled={disabled}
        onClick={() => onMore(catalog.next_offset!)}>Следующая страница</button>}
    </>}
  </section>;
}
