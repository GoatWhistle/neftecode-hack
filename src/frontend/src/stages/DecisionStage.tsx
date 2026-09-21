import { num } from "../format";
import { Empty, LampDot, Note, Readout, Tag } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { RefusalPanel } from "../ui/Refusal";
import { ActionBlock, VerdictHead } from "../ui/Verdict";
import type { StageProps } from "./StateStage";

const RISK_TONE: Record<string, "pass" | "unknown" | "fail"> = {
  none: "pass",
  low: "pass",
  medium: "unknown",
  high: "fail"
};

export function DecisionStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const decision = payload.decision;
  const explanation = payload.explanation;
  const refused = decision.status === "refuse";
  const action = decision.immediate_action;
  const warnings = explanation.warnings ?? [];
  const risk = explanation.risk;
  const limits = explanation.limits ?? [];
  const deployment = decision.deployment_readiness;

  return (
    <Section
      id="decision"
      index={index}
      state={state}
      source={source}
      title="Решение"
      lead={
        refused
          ? "Отказ — это результат расчёта, а не сбой: ниже сказано, чего именно недостаёт."
          : "Что оператору сделать прямо сейчас, с чем считаться и чего расчёт не покрывает."
      }
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
      final
    >
      <VerdictHead payload={payload} refused={refused} />

      {deployment === undefined ? (
        <div className="gatebar">
          <p className="gatebar__head">Готовность не подтверждена</p>
          <p className="gatebar__text">
            Готовность к промышленному применению сервер не передавал: судить по этому прогону нельзя.
          </p>
        </div>
      ) : !deployment.ready ? (
        <div className="gatebar">
          <p className="gatebar__head">Промышленное применение заблокировано</p>
          <ul className="gatebar__list">
            {deployment.required_inputs.map((item) => (
              <li key={item.label}>{item.label}</li>
            ))}
          </ul>
          <p className="gatebar__text">
            Числа 4000 т и 30 т/ч остаются только сценарными допущениями.
          </p>
        </div>
      ) : null}

      {refused ? (
        <RefusalPanel payload={payload} />
      ) : action ? (
        <ActionBlock payload={payload} action={action} />
      ) : (
        <Empty>Немедленное действие не передавалось: советовать нечего.</Empty>
      )}

      <div className="final__ledger">
        <p className="final__kicker">Чего это стоит</p>
        <div className="readouts">
          <Readout
            label="Проверок пройдено"
            value={
              explanation.checks_passed !== undefined && explanation.checks_total !== undefined
                ? `${explanation.checks_passed} из ${explanation.checks_total}`
                : "не передавалось"
            }
            tone={explanation.checks_passed === explanation.checks_total ? "pass" : "unknown"}
          />
          <Readout label="Выпуск за горизонт" value={num(decision.production_t, 1)} unit="т" />
          <Readout
            label="Стоимость тонны"
            value={num(decision.cost_per_tonne, 4)}
            unit="у.е./т"
            hint="в условных единицах сценария"
          />
          <Readout
            label="Товарный выпуск"
            value={decision.commercial_release_allowed ? "разрешён" : "не разрешён"}
            tone={decision.commercial_release_allowed ? "pass" : "fail"}
          />
        </div>
      </div>

      <div className="final__why">
        <p className="final__kicker">Почему так, и чего расчёт не утверждает</p>

        {risk ? (
          <div className="risk">
            <p className="risk__head">
              <LampDot state={RISK_TONE[risk.level] ?? "unknown"} />
              Риск: {risk.level}
            </p>
            <p className="risk__headline">{risk.headline}</p>
            {risk.items.length > 0 ? (
              <ul className="risk__items">
                {risk.items.map((item) => (
                  <li key={item.kind}>
                    <Tag tone={RISK_TONE[item.level] ?? "unknown"}>{item.level}</Tag> {item.text}
                    {item.missing?.length ? (
                      <span className="refusal__sub">Не получено: {item.missing.join("; ")}</span>
                    ) : null}
                    {item.sources?.length ? (
                      <span className="refusal__sub">Источники вне доверия: {item.sources.join(", ")}</span>
                    ) : null}
                    {item.perturbations?.length ? (
                      <span className="refusal__sub">Отклонения: {item.perturbations.join("; ")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>Перечня отдельных рисков не передавали.</Empty>
            )}
            {risk.scope ? <Note>{risk.scope}</Note> : null}
          </div>
        ) : (
          <Empty>Оценка риска не передавалась — это не значит, что риска нет.</Empty>
        )}

        {warnings.length > 0 ? (
          <div className="warnings">
            {warnings.map((warning) => (
              <div key={warning.kind} className="warnings__item">
                <p className="warnings__text">{warning.text}</p>
                {warning.observed_margin_mgkg !== undefined ? (
                  <div className="readouts">
                    <Readout
                      label="Фактический запас"
                      value={num(warning.observed_margin_mgkg, 3)}
                      unit="мг/кг"
                      tone="unknown"
                    />
                    <Readout
                      label="Технологический запас"
                      value={num(warning.operating_margin_mgkg, 2)}
                      unit="мг/кг"
                      hint="держат на установке"
                    />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {limits.length > 0 ? (
          <div className="limits">
            <p className="limits__head">Чего расчёт не утверждает</p>
            <ul className="limits__list">
              {limits.map((limit) => (
                <li key={limit}>{limit}</li>
              ))}
            </ul>
          </div>
        ) : (
          <Empty>Перечень оговорок расчёта не передавался.</Empty>
        )}

        {decision.note ? <Note>{decision.note}</Note> : null}
      </div>

      <JsonPanel title="JSON: решение и объяснение оператору" value={{ decision, explanation }} />
    </Section>
  );
}
