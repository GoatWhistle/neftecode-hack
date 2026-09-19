import type { OptimizerRound } from "../types";
import { familyOf, num } from "../format";

function familyTotals(rounds: OptimizerRound[]): [string, number][] {
  const totals = new Map<string, number>();
  for (const round of rounds) {
    for (const [family, count] of Object.entries(round.veto_families ?? {})) {
      const label = familyOf(family);
      totals.set(label, (totals.get(label) ?? 0) + count);
    }
  }
  return [...totals.entries()].sort((a, b) => b[1] - a[1]);
}

function RoundBar({ round }: { round: OptimizerRound }) {
  const proposed = round.proposed ?? 0;
  const feasible = round.feasible ?? 0;
  const share = proposed > 0 ? (feasible / proposed) * 100 : 0;
  return (
    <li className="funnel__round">
      <span className="funnel__label">Раунд {round.round}</span>
      <span className="funnel__bar" role="img"
        aria-label={`Раунд ${round.round}: предложено ${proposed}, допустимо ${feasible}`}>
        <span className="funnel__proposed">
          <span className="funnel__feasible" style={{ width: `${share}%` }} />
        </span>
      </span>
      <span className="funnel__counts">
        допустимо <b>{num(feasible, 0)}</b> из <b>{num(proposed, 0)}</b> предложенных
      </span>
    </li>
  );
}

export interface VetoFunnelProps {
  rounds: OptimizerRound[];
  compact?: boolean;
}

export function VetoFunnel({ rounds, compact = false }: VetoFunnelProps) {
  if (rounds.length === 0) return null;
  const families = familyTotals(rounds);
  const vetoTotal = families.reduce((acc, [, count]) => acc + count, 0);
  const proposedTotal = rounds.reduce((acc, round) => acc + (round.proposed ?? 0), 0);
  const widest = families.length > 0 ? Math.max(...families.map(([, count]) => count)) : 0;

  return (
    <div className={`funnel ${compact ? "funnel--compact" : ""}`}>
      {compact ? null : (
        <>
          <p className="funnel__head">
            {rounds.length > 1 ? "Отсев планов по раундам" : "Отсев планов: раунд один"}
          </p>
          <ul className="funnel__rounds">
            {rounds.map((round) => (
              <RoundBar key={round.round} round={round} />
            ))}
          </ul>
          {rounds.length === 1 ? (
            <p className="funnel__single">
              Раунд один: сужения поиска не потребовалось. Воронки из одной ступени не бывает — второй
              ступени здесь нет не потому, что её обрезали, а потому, что допустимые планы нашлись сразу и
              оптимизатор не добавлял ограничений к следующему проходу.
            </p>
          ) : null}
        </>
      )}

      {families.length > 0 ? (
        <>
          <p className="funnel__head">Вето проверок по семействам ограничений</p>
          <ul className="funnel__families">
            {families.map(([family, count]) => (
              <li key={family} className="funnel__family">
                <span className="funnel__label">{family}</span>
                <span className="funnel__bar" role="img" aria-label={`${family}: ${count} вето проверок`}>
                  <span
                    className="funnel__veto"
                    style={{ width: widest > 0 ? `${(count / widest) * 100}%` : "0%" }}
                  />
                </span>
                <span className="funnel__counts">
                  <b>{num(count, 0)}</b> вето проверок
                </span>
              </li>
            ))}
          </ul>
          <p className="funnel__warn">
            Эти полосы нормированы отдельно от полос планов выше и в одну шкалу с ними не сводятся.
            Семейства насчитали {num(vetoTotal, 0)} вето при {num(proposedTotal, 0)} предложенных
            планах, потому что здесь считаются отклонённые проверки, а не планы: один план нарушает
            сразу несколько ограничений в нескольких точках горизонта.
          </p>
        </>
      ) : null}
    </div>
  );
}
