import { useState } from "react";
import type { HistorySelection } from "./types";
import { localTime, longMoment } from "./moment";

interface Props {
  coverage: { start: string; end: string; model_valid_from: string };
  gridMinutes: number;
  onSelect: (selection: HistorySelection) => void;
  disabled: boolean;
}

export function coverageMin(coverage: Props["coverage"]): string {
  const lower = coverage.start > coverage.model_valid_from ? coverage.start : coverage.model_valid_from;
  return lower.length === 10 ? `${lower}T00:00:00` : lower;
}

export const canonical = (value: string) => value.length === 16 ? `${value}:00` : value;

/** Точная дата: поле, доступный диапазон и выбор. Подробности методики — в раскрытии. */
export function HistoryMoment({ coverage, gridMinutes, onSelect, disabled }: Props) {
  const [at, setAt] = useState("");
  const min = coverageMin(coverage);
  const valid = at !== "" && canonical(at) >= min && canonical(at) <= coverage.end;
  return <div className="history__exact">
    <div className="history__exact-row">
      <label>Местное время решения<input type="datetime-local" step="1" min={min} max={coverage.end}
        value={at} onChange={(event) => setAt(event.target.value)} /></label>
      <button type="button" className="history__primary" disabled={disabled || !valid}
        onClick={() => onSelect({ kind: "moment", requested_at: at })}>Выбрать точный момент</button>
    </div>
    <p className="history__hint">Доступно: {longMoment(min)} — {longMoment(coverage.end)}.
      {at && !valid && " Выбранное время вне доступного диапазона."}</p>
    <p className="history__lead">Используются только измерения, доступные к выбранному моменту.</p>
    <details className="history__method"><summary>Как выбираются данные</summary>
      <p>Время местное, как в исходных данных; часовой пояс в поставке не указан.</p>
      <p>Телеметрия: {localTime(coverage.start)} — {localTime(coverage.end)}; модель доступна с {localTime(coverage.model_valid_from)}.</p>
      <p>Шаг телеметрии обычно {gridMinutes} минут. Момент сохраняется точно, без округления до сетки;
        доступность подтвердит сервер при запуске.</p>
      <p>ЛИМС учитывается только после принятой задержки публикации, указанной в происхождении данных.</p>
    </details>
  </div>;
}
