import { useState } from "react";
import type { HistorySelection } from "./types";

interface Props {
  coverage: { start: string; end: string; model_valid_from: string };
  onSelect: (selection: HistorySelection) => void;
  onOverview: ((start: string, end: string) => void) | undefined;
  disabled: boolean;
}

export function HistoryMoment({ coverage, onSelect, onOverview, disabled }: Props) {
  const [at, setAt] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const lower = coverage.start > coverage.model_valid_from ? coverage.start : coverage.model_valid_from;
  const min = lower.length === 10 ? `${lower}T00:00:00` : lower;
  const canonical = (value: string) => value.length === 16 ? `${value}:00` : value;
  const valid = at !== "" && canonical(at) >= min && canonical(at) <= coverage.end;
  const validPeriod = start !== "" && end !== "" && canonical(start) >= min && canonical(end) <= coverage.end && canonical(start) <= canonical(end);
  return <div className="history__moment">
    <p>Телеметрия: {coverage.start.replace("T", " ")} — {coverage.end.replace("T", " ")}.
      Модель доступна с {coverage.model_valid_from.replace("T", " ")}.</p>
    <p>Шаг телеметрии обычно 10 минут. Момент сохраняется точно, используются только уже доступные измерения.
      ЛИМС учитывается после принятой задержки публикации, указанной в происхождении данных.</p>
    <label>Местное время решения<input type="datetime-local" step="1" min={min} max={coverage.end}
      value={at} onChange={(event) => setAt(event.target.value)} /></label>
    <button type="button" disabled={disabled || !valid}
      onClick={() => onSelect({ kind: "moment", requested_at: at })}>Выбрать точный момент</button>
    {at && <p>Запрошено: {at.replace("T", " ")}. Без округления; доступность подтвердит сервер при запуске.</p>}
    {onOverview && <details><summary>Обзор периода без расчёта решения</summary>
      <label>Начало периода<input type="datetime-local" min={min} max={coverage.end} value={start}
        onChange={(event) => setStart(event.target.value)} /></label>
      <label>Конец периода<input type="datetime-local" min={min} max={coverage.end} value={end}
        onChange={(event) => setEnd(event.target.value)} /></label>
      <button type="button" disabled={disabled || !validPeriod} onClick={() => onOverview(start, end)}>
        Показать наблюдения</button>
      <p>До 48 точек за запрос; прогноз и решение для точек обзора не вычисляются.</p>
    </details>}
  </div>;
}
