import { MISSING } from "../format";
import { isOriginKey, originMeta } from "../provenance";

export interface OriginBadgeProps {
  origin: string | null | undefined;
  label?: string | undefined;
}

export function OriginBadge({ origin, label }: OriginBadgeProps) {
  const meta = originMeta(origin);
  if (!meta) {
    const absent = "Происхождение величины в payload не передавалось";
    return (
      <span className="origin origin--absent" role="note" title={absent} aria-label={absent}>
        {label ? `${label}: ` : ""}
        {MISSING}
      </span>
    );
  }
  const key = isOriginKey(origin) ? origin : "open";
  return (
    <span
      className={`origin origin--${key}`}
      role="note"
      title={meta.full}
      aria-label={`${label ? `${label}: ` : ""}${meta.full}`}
    >
      {label ? `${label}: ` : ""}
      {meta.short}
    </span>
  );
}

export function OriginLegend() {
  return (
    <p className="origin-legend">
      <span className="origin-legend__head">Происхождение чисел:</span>
      <OriginBadge origin="given" />
      <span className="origin-legend__text">требование ТЗ или ответ эксперта</span>
      <OriginBadge origin="derived" />
      <span className="origin-legend__text">рассчитано (не измерение); сценарный расчёт тоже помечается так</span>
      <OriginBadge origin="measured" />
      <span className="origin-legend__text">измерение с установки</span>
      <OriginBadge origin="scenario" />
      <span className="origin-legend__text">допущение сценария, не измерение</span>
      <OriginBadge origin="open" />
      <span className="origin-legend__text">не определено</span>
    </p>
  );
}
