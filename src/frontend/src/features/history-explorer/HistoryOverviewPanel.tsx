import type { HistoryOverview } from "./types";

interface Props {
  overview: HistoryOverview;
  onMore: ((offset: number) => void) | undefined;
  disabled: boolean;
}

const SCOPES: Record<string, string> = { column: "Колонка", telemetry: "Телеметрия",
  pak: "ПАК", pak_lab_sample: "Конфликт на пробе ПАК/ЛИМС" };

export function HistoryOverviewPanel({ overview, onMore, disabled }: Props) {
  const exclusions = overview.exclusions;
  const display = (value: number | null) => value === null ? "нет измерения" : value.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
  return <details className="history__overview"><summary>Наблюдения периода: {overview.points.length} точек</summary>
    <p>{overview.note}</p>
    <div className="history__table" tabIndex={0} role="region" aria-label="Наблюдения периода">
      <table><caption>Наблюдения, без оценки пригодности источников</caption><thead><tr>
        <th>Момент</th><th>ЛИМС, мг/кг</th><th>ЛИМС доступен с</th><th>ПАК, ppm</th>
      </tr></thead><tbody>{overview.points.map((point, i) => <tr key={`${point.at}-${i}`}>
        <td>{point.at.replace("T", " ")}</td><td title={String(point.lab_value)}>{display(point.lab_value)}</td>
        <td>{point.lab_available_time?.replace("T", " ") ?? "нет даты"}</td>
        <td title={String(point.pak_value)}>{display(point.pak_value)}</td>
      </tr>)}</tbody></table>
    </div>
    <details><summary>Исключения источников: {exclusions.total}</summary>
      <p>{exclusions.note}</p>
      {!exclusions.provenance.available && <p>Реестр исключений не поставлен; отсутствие списка не означает отсутствие сбоев.</p>}
      {exclusions.items.map((item, i) => <p key={`${item.start}-${item.scope}-${i}`}>
        {SCOPES[item.scope] ?? item.scope}{item.column ? ` ${item.column}` : ""}: {item.start.replace("T", " ")} — {item.end.replace("T", " ")}: {item.reason}
      </p>)}
      {exclusions.next_offset !== null && onMore && <button type="button" disabled={disabled}
        onClick={() => onMore(exclusions.next_offset!)}>Следующие исключения</button>}
    </details>
  </details>;
}
