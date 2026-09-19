import { controlLabel, controlUnit, hours, num } from "../format";
import { Empty, Field, Fields, LampDot, Note, Readout, Tag } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { RefusalPanel } from "../ui/Refusal";
import { OriginBadge } from "../ui/Origin";
import { stockLine } from "../provenance";
import type { StageProps } from "./StateStage";

const RISK_TONE: Record<string, "pass" | "unknown" | "fail"> = {
  none: "pass",
  low: "pass",
  medium: "unknown",
  high: "fail"
};

export function DecisionStage({ payload, index, state, source }: StageProps) {
  const decision = payload.decision;
  const explanation = payload.explanation;
  const refused = decision.status === "refuse";
  const action = decision.immediate_action;
  const warnings = explanation.warnings ?? [];
  const risk = explanation.risk;
  const names = explanation.component_names ?? {};

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
      lamp={refused ? "fail" : warnings.length > 0 ? "unknown" : "pass"}
      lampTitle={payload.status_label}
    >
      <div className={`verdict verdict--${refused ? "refuse" : "ok"}`}>
        <p className="verdict__label">{payload.status_label}</p>
        <p className="verdict__reason">{decision.reason}</p>
        {decision.scope ? <p className="verdict__scope">{decision.scope}</p> : null}
      </div>

      {refused ? (
        <RefusalPanel payload={payload} />
      ) : action ? (
        <>
          <div className="readouts readouts--action">
            {Object.entries(action.controls ?? {}).map(([key, value]) => (
              <Readout
                key={key}
                label={controlLabel(key)}
                value={num(value, 1)}
                unit={controlUnit(key)}
                badge={<OriginBadge origin="derived" />}
              />
            ))}
            <Readout
              label="Производительность"
              value={num(action.throughput_tph, 1)}
              unit="т/ч"
              badge={<OriginBadge origin="derived" />}
            />
            <Readout
              label="Доза присадки"
              value={num(action.additive_dose, 3)}
              unit="кг/т"
              badge={<OriginBadge origin="derived" />}
            />
          </div>
          <Fields>
            <Field label="Момент действия">{hours(action.time_hours)}</Field>
            <Field label="Рецепт смешения">
              {Object.entries(action.recipe ?? {}).map(([key, value]) => (
                <span key={key} className="chip">
                  {names[key] ?? key} <b>{num(value, 3)}</b>
                </span>
              ))}
            </Field>
            <Field label="Откуда берут компоненты">
              {Object.keys(action.recipe ?? {}).map((key) => {
                const line = stockLine(payload, key);
                return (
                  <span key={key} className="chip">
                    {names[key] ?? key} <b>{line.text}</b>
                  </span>
                );
              })}
            </Field>
            <Field label="Проверок пройдено">
              {explanation.checks_passed ?? "—"} из {explanation.checks_total ?? "—"}
            </Field>
            <Field label="Товарный выпуск разрешён">{decision.commercial_release_allowed ? "да" : "нет"}</Field>
          </Fields>
        </>
      ) : (
        <Empty>Немедленное действие не передавалось.</Empty>
      )}

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
          ) : null}
          {risk.scope ? <Note>{risk.scope}</Note> : null}
        </div>
      ) : null}

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

      {explanation.limits?.length ? (
        <div className="limits">
          <p className="limits__head">Чего расчёт не утверждает</p>
          <ul className="limits__list">
            {explanation.limits.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {decision.note ? <Note>{decision.note}</Note> : null}

      <JsonPanel title="JSON: решение и объяснение оператору" value={{ decision, explanation }} />
    </Section>
  );
}
