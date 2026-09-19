import type { OptimizerRound, TraceEvent } from "../types";
import { num } from "../format";
import { Empty, Note, Readout, Scroller } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import type { StageProps } from "./StateStage";

interface OptimizerTrace extends TraceEvent {
  rounds?: OptimizerRound[];
  max_rounds?: number;
  evaluated?: number;
  note?: string;
}

export function CandidatesStage({ payload, index, state, source }: StageProps) {
  const trace = (payload.decision.trace ?? []).find((item) => item.agent === "optimizer") as
    | OptimizerTrace
    | undefined;
  const rounds = trace?.rounds ?? [];
  const evaluated = trace?.evaluated ?? null;
  const feasible = rounds.reduce((acc, round) => acc + (round.feasible ?? 0), 0);
  const alternatives = payload.decision.alternatives ?? [];

  return (
    <Section
      id="candidates"
      index={index}
      state={state}
      source={source}
      title="Кандидаты"
      lead="Сколько планов оптимизатор построил и проверил, и по каким семействам ограничений они отсеялись."
      lamp={rounds.length === 0 ? "unknown" : feasible > 0 ? "pass" : "fail"}
      lampTitle={feasible > 0 ? "допустимые планы есть" : "допустимых планов не нашлось"}
    >
      {rounds.length === 0 ? (
        <Empty>Трасса оптимизатора не передавалась.</Empty>
      ) : (
        <>
          <div className="readouts">
            <Readout label="Планов рассмотрено" value={num(evaluated, 0)} hint="суммарно по раундам" />
            <Readout
              label="Прошли все проверки"
              value={num(feasible, 0)}
              tone={feasible > 0 ? "pass" : "fail"}
              hint="допустимых кандидатов"
            />
            <Readout label="Раундов поиска" value={`${rounds.length} из ${num(trace?.max_rounds, 0)}`} />
            <Readout label="Показано альтернатив" value={String(alternatives.length)} hint="до пяти в payload" />
          </div>

          <Scroller label="Отсев по раундам">
            <table className="grid">
              <caption>Отсев по раундам: сколько запретов дало каждое семейство ограничений</caption>
              <thead>
                <tr>
                  <th scope="col">Раунд</th>
                  <th scope="col">Предложено</th>
                  <th scope="col">Допустимо</th>
                  <th scope="col">Вето качества</th>
                  <th scope="col">Вето надёжности</th>
                  <th scope="col">Семейства</th>
                </tr>
              </thead>
              <tbody>
                {rounds.map((round) => (
                  <tr key={round.round}>
                    <th scope="row">{round.round}</th>
                    <td className="grid__num">{num(round.proposed, 0)}</td>
                    <td className="grid__num">{num(round.feasible, 0)}</td>
                    <td className="grid__num">{num(round.quality_vetoed, 0)}</td>
                    <td className="grid__num">{num(round.reliability_vetoed, 0)}</td>
                    <td>
                      {Object.entries(round.veto_families ?? {}).map(([family, count]) => (
                        <span key={family} className="chip">
                          {family} <b>{num(count, 0)}</b>
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>

          <Note>
            Число проверенных планов — это фактический перебор. Объявленный бюджет поиска на экран
            намеренно не вынесен: он расходуется не полностью и завысил бы полноту перебора.
          </Note>
          {trace?.note ? <Note>{trace.note}</Note> : null}
        </>
      )}

      <JsonPanel title="JSON: трасса оптимизатора" value={trace ?? null} openTo={2} />
    </Section>
  );
}
