import { useEffect, useState } from "react";
import type { HistoryCatalog, HistoryItem, HistorySelection } from "./types";
import { KIND_LABEL, kindOf, localTime, longMoment, shortMoment } from "./moment";

interface Props {
  catalog: HistoryCatalog;
  selection: HistorySelection | null;
  current: string | null;
  onUse: (selection: HistorySelection) => void;
  onMore?: ((offset: number) => void) | undefined;
  disabled: boolean;
}

const TAG_UNITS: Record<string, string> = { "ht.T6": "°C", "ht.F9": "т/ч", "ht.F26": "м³/ч" };
const NARROW = "(max-width: 760px)";

function number(value: number): string {
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
}

function reading(value: number | null, unit: string): string {
  return value === null ? "нет измерения" : `${number(value)} ${unit}`;
}

/** На телефоне подробности раскрываются под строкой, на широком экране — справа от списка. */
function narrowQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(NARROW) : null;
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => narrowQuery()?.matches ?? false);
  useEffect(() => {
    const query = narrowQuery();
    if (!query) return;
    const update = () => setNarrow(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return narrow;
}

function EpisodeDetail({ item, applied, disabled, onUse }: {
  item: HistoryItem; applied: boolean; disabled: boolean; onUse: () => void;
}) {
  const kind = kindOf(item);
  return <div className="episode" aria-label={`Подробности: ${item.label}`} role="region">
    <p className="episode__label">{item.label}</p>
    <p className="episode__date">{longMoment(item.at)}</p>
    <p className={`episode__kind episode__kind--${kind}`}>{KIND_LABEL[kind]}</p>
    {item.synthetic_edits.length > 0 && <p className="episode__edits">Изменено: {item.synthetic_edits.join("; ")}</p>}
    <dl className="episode__facts">
      <div><dt>ЛИМС</dt><dd title={String(item.facts.lab_value)}>{reading(item.facts.lab_value, "мг/кг")}</dd></div>
      <div><dt>ПАК</dt><dd title={String(item.facts.pak_value)}>{reading(item.facts.pak_value, "ppm")}</dd></div>
    </dl>
    <details className="episode__more"><summary>Измерения и происхождение</summary>
      {item.facts.lab_available_time && <p>ЛИМС доступен с {localTime(item.facts.lab_available_time)}</p>}
      <p>Доля пропусков телеметрии: {item.facts.telemetry_missing_fraction === null
        ? "не передана" : `${(100 * item.facts.telemetry_missing_fraction).toFixed(1)} %`}</p>
      {Object.entries(item.measurements).map(([tag, value]) => <p key={tag}>
        {tag}: {value ? `${number(value.value)} ${TAG_UNITS[tag] ?? "(единица не передана)"} · ${localTime(value.time)} · возраст ${value.age_min} мин` : "нет измерения"}
      </p>)}
      <p>Срез: <code>{item.snapshot}</code></p>
      {item.provenance.model_fingerprint && <p>Модель: <code>{item.provenance.model_fingerprint}</code></p>}
    </details>
    <button type="button" className="history__primary" disabled={disabled || applied} onClick={onUse}>
      {applied ? "Этот момент уже выбран" : "Использовать этот момент"}</button>
  </div>;
}

export function EpisodeList({ catalog, selection, current, onUse, onMore, disabled }: Props) {
  const narrow = useNarrow();
  const [filter, setFilter] = useState("");
  const [preview, setPreview] = useState<string | null>(current ?? catalog.items[0]?.snapshot ?? null);
  const needle = filter.toLocaleLowerCase();
  const items = catalog.items.filter((item) =>
    `${item.at} ${localTime(item.at)} ${shortMoment(item.at, true)} ${item.label}`.toLocaleLowerCase().includes(needle));
  const years = new Set(catalog.items.map((item) => item.at.slice(0, 4)));
  const shown = items.find((item) => item.snapshot === preview) ?? (narrow ? null : items[0] ?? null);
  const appliedKey = selection?.kind === "snapshot" ? selection.snapshot : current;
  const detail = (item: HistoryItem) => <EpisodeDetail item={item} disabled={disabled}
    applied={appliedKey === item.snapshot}
    onUse={() => onUse({ kind: "snapshot", snapshot: item.snapshot, requested_at: item.at })} />;

  return <div className="episodes">
    <label className="history__search">
      <span className="history__visually-hidden">Поиск по дате или названию</span>
      <input type="search" placeholder="Поиск по дате или названию" value={filter}
        onChange={(event) => setFilter(event.target.value)} />
    </label>
    <div className="episodes__body">
      <ul className="episodes__list">
        {items.map((item) => {
          const active = shown?.snapshot === item.snapshot;
          return <li key={item.snapshot}>
            <button type="button" className="episodes__row" aria-pressed={active} aria-expanded={narrow ? active : undefined}
              onClick={() => setPreview(narrow && active ? null : item.snapshot)}>
              <span className="episodes__when">{shortMoment(item.at, years.size > 1)}</span>
              <span className="episodes__name">{item.label}</span>
              {item.synthetic_edits.length > 0 && <span className="episodes__tag">изменён</span>}
              {appliedKey === item.snapshot && <span className="episodes__tag episodes__tag--on">выбран</span>}
            </button>
            {narrow && active && detail(item)}
          </li>;
        })}
      </ul>
      {!narrow && shown && detail(shown)}
    </div>
    {items.length === 0 && <p>Подходящих эпизодов нет.</p>}
    <p className="history__hint">Показано {items.length} из {catalog.total}.
      {catalog.snapshot_coverage && ` Эпизоды: ${longMoment(catalog.snapshot_coverage.start)} — ${longMoment(catalog.snapshot_coverage.end)}; между ними данных может не быть.`}</p>
    {catalog.next_offset !== null && onMore && <button type="button" className="history__ghost" disabled={disabled}
      onClick={() => onMore(catalog.next_offset!)}>Следующая страница</button>}
  </div>;
}
