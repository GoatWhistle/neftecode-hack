import { duration } from "../format";
import { useLiveClock } from "../useLiveClock";
import type { BudgetRow, ProviderBand } from "../run/agentMeters";
import { BUDGET_CELL_MAX } from "../run/agentMeters";
import { CONSTRAINT_TEXT, CONSTRAINT_VOCABULARY } from "../run/agentVocab";
import type { ConstraintPick } from "../run/agentActs";

export function ProviderStrip({ band, label }: { band: ProviderBand | null; label?: string | undefined }) {
  if (band === null) {
    return (
      <p className="provider provider--unknown">
        <span className="provider__mark" aria-hidden="true" />
        <span className="provider__name">провайдер не передавался</span>
        <span className="provider__status">источник решения неизвестен</span>
      </p>
    );
  }
  const mode = band.deterministic ? "scripted" : "live";
  return (
    <p className={`provider provider--${mode}`}>
      <span className="provider__mark" aria-hidden="true" />
      <span className="provider__name">
        {band.provider} · {band.model}
      </span>
      <span className="provider__status">
        {band.deterministic ? "детерминированная политика" : "живая модель"}
      </span>
      {label ? <span className="provider__label">{label}</span> : null}
    </p>
  );
}

function Segments({ row }: { row: BudgetRow }) {
  if (row.limit === null) return null;
  const total = Math.max(row.limit, row.used);
  if (total > BUDGET_CELL_MAX) return null;
  const cells = Array.from({ length: total }, (_, index) => index < row.used);
  return (
    <span className="budget__bar" aria-hidden="true">
      {cells.map((filled, index) => (
        <span key={index} className={`budget__cell${filled ? " budget__cell--used" : ""}`} />
      ))}
    </span>
  );
}

function counterText(row: BudgetRow): string {
  return row.exact ? "счётчик сервера" : "подсчёт по событиям";
}

function sharedCounter(rows: BudgetRow[]): string | null {
  if (rows.length === 0) return null;
  const first = counterText(rows[0] as BudgetRow);
  return rows.every((row) => counterText(row) === first) ? first : null;
}

function originLine(rows: BudgetRow[], shared: string | null): string | null {
  if (shared === null) return null;
  const withLimit = rows.filter((row) => row.limit !== null).length;
  if (withLimit === rows.length) return `${shared}, предел от сервера`;
  if (withLimit === 0) return `${shared}, предел не передавался`;
  return `${shared}; предел от сервера там, где он показан`;
}

function Rows({ rows }: { rows: BudgetRow[] }) {
  const shared = sharedCounter(rows);
  const line = originLine(rows, shared);
  const mixedLimits = rows.some((row) => row.limit === null) && rows.some((row) => row.limit !== null);
  return (
    <>
      <ul className="budget__rows">
        {rows.map((row) => (
          <li key={row.role} className={`budget__row${row.spent ? " budget__row--spent" : ""}`}>
            <span className="budget__label">
              {row.label} {row.limit === null ? row.used : `${row.used}/${row.limit}`}
            </span>
            <Segments row={row} />
            {row.spent ? <span className="budget__spent">исчерпано</span> : null}
            {shared === null ? <span className="budget__origin">{counterText(row)}</span> : null}
            {mixedLimits && row.limit === null ? (
              <span className="budget__origin">предела нет</span>
            ) : null}
          </li>
        ))}
      </ul>
      {line === null ? null : <p className="budget__origin budget__origin--group">Происхождение счётчиков группы: {line}</p>}
    </>
  );
}

export interface BudgetMeterProps {
  rows: BudgetRow[];
  total: BudgetRow | null;
  spend: BudgetRow[];
}

export function BudgetMeter({ rows, total, spend }: BudgetMeterProps) {
  const calls = total === null ? rows : [...rows, total];
  if (calls.length === 0 && spend.length === 0) return null;
  const exhausted = [...calls, ...spend].some((row) => row.spent);
  return (
    <div className="budget">
      <p className="budget__caption">
        Потолок ходов: сколько обращений к модели уже потрачено из отведённых
      </p>
      {calls.length > 0 ? <Rows rows={calls} /> : null}
      {spend.length > 0 ? (
        <>
          <p className="budget__caption">
            Прочие лимиты поиска: консультации, повторные поиски, прогоны устойчивости
          </p>
          <Rows rows={spend} />
        </>
      ) : null}
      {exhausted ? (
        <p className="budget__note">
          Исчерпанный счётчик объясняет, почему агент перестал искать дальше.
        </p>
      ) : null}
    </div>
  );
}

export function ConstraintVocabulary({ picks, note }: { picks: ConstraintPick[]; note: string | null }) {
  return (
    <div className="vocab">
      <p className="vocab__caption">словарь ограничений: агент выбирает из семи типов</p>
      <ul className="vocab__list">
        {picks.map((pick) => (
          <li
            key={pick.type}
            className={`vocab__pill${pick.proposed ? " vocab__pill--picked" : ""}`}
            title={pick.type}
          >
            <span className="vocab__name">{pick.label}</span>
            {pick.value ? <span className="vocab__value">{pick.value}</span> : null}
          </li>
        ))}
      </ul>
      {note ? <p className="vocab__note">{note}</p> : null}
    </div>
  );
}

export function emptyPicks(): ConstraintPick[] {
  return CONSTRAINT_VOCABULARY.map((type) => ({
    type,
    label: CONSTRAINT_TEXT[type] ?? type,
    proposed: false,
    value: null
  }));
}

export function WaitingCounter({ elapsedMs, sinceMs, lastFrameAt }: {
  elapsedMs: number;
  sinceMs: number;
  lastFrameAt: number | null;
}) {
  const liveMs = useLiveClock(elapsedMs, lastFrameAt ?? null, true);
  const held = Math.max(0, liveMs - sinceMs);
  return (
    <p className="waiting" role="status">
      <span className="waiting__mark" aria-hidden="true" />
      ждём ответа модели, {duration(held)}
    </p>
  );
}
