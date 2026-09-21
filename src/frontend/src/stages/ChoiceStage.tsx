import type { Alternative } from "../types";
import { controlLabel, controlUnit, hours, isNumber, num, percent } from "../format";
import { Empty, Field, Fields, Note, Readout, Scroller, Tag } from "../ui/Primitives";
import { OriginBadge } from "../ui/Origin";
import { onDemandIds } from "../provenance";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { OffspecBlock } from "../ui/OffspecBlock";
import { RobustnessMap } from "../ui/RobustnessMap";
import { PlanDiff } from "../ui/PlanDiff";
import type { StageProps } from "./StateStage";

const RANK_LABEL: Record<string, string> = {
  "-production_t": "больший выпуск",
  production_t: "меньший выпуск",
  cost_per_tonne: "меньшая стоимость тонны",
  "-cost_per_tonne": "большая стоимость тонны",
  severity_index: "меньшая тяжесть режима",
  "-severity_index": "большая тяжесть режима",
  changes: "меньше изменений уставок",
  "-changes": "больше изменений уставок",
  candidate_id: "номер кандидата — на случай полного равенства"
};

function rankLabel(key: string): string {
  return RANK_LABEL[key] ?? key;
}

export function ChoiceStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const plan = payload.decision.selected_plan;
  const candidates = payload.decision.alternatives ?? [];
  const setpointsOf = new Map(candidates.map((item) => [item.candidate_id, item]));
  const alternatives: Alternative[] = (
    payload.explanation.alternatives ??
    candidates.map<Alternative>((item) => ({
      candidate_id: item.candidate_id,
      production_t: item.production_t,
      cost_per_tonne: item.cost_per_tonne,
      severity_index: item.severity_index,
      changes: item.changes,
      why_not: item.rejection_reasons?.length
        ? `Не проходит жёсткие ограничения: ${item.rejection_reasons.slice(0, 2).join("; ")}`
        : "Сравнение с выбранным планом в payload не передавалось"
    }))
  ).map((item) => {
    const source = setpointsOf.get(item.candidate_id);
    if (!source) return item;
    return {
      ...item,
      controls: item.controls ?? source.controls,
      recipe: item.recipe ?? source.recipe,
      throughput_tph: item.throughput_tph ?? source.throughput_tph,
      additive_dose: item.additive_dose ?? source.additive_dose
    };
  });
  const baseline = plan?.steps?.[0] ?? payload.decision.immediate_action ?? null;
  const stepOrigins = payload.explanation.plan_origin?.steps ?? [];
  const originForStep = (timeHours: number) =>
    stepOrigins.find((entry) => entry.time_hours === timeHours) ?? null;
  const withSetpoints = alternatives.filter((item) => item.controls || item.recipe).length;
  const rule = payload.explanation.comparison_rule;
  const policy = payload.decision.selection_policy;
  const names = payload.explanation.component_names ?? {};
  const demand = onDemandIds(payload);
  const usesDemand = demand.some((id) => (payload.decision.immediate_action?.recipe?.[id] ?? 0) > 0);

  return (
    <Section
      id="choice"
      index={index}
      state={state}
      source={source}
      title="Выбор"
      lead="Какой план победил, и чем именно проигрывает каждый из остальных."
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      {plan ? (
        <>
          <div className="readouts">
            <Readout label="Выбранный план" value={plan.plan_id} hint={plan.intent} />
            <Readout
              label="Выпуск за горизонт"
              value={num(payload.decision.production_t, 1)}
              unit="т"
              tone="pass"
              badge={<OriginBadge origin="derived" />}
            />
            <Readout
              label="Стоимость тонны"
              value={num(payload.decision.cost_per_tonne, 4)}
              unit="у.е./т"
              badge={<OriginBadge origin="derived" />}
              hint="в условных единицах сценария"
            />
            <Readout label="Тяжесть режима" value={num(payload.decision.severity_index, 3)} hint="сводный индекс" />
            <Readout label="Изменений уставок" value={num(plan.changes, 0)} hint="от текущего режима" />
          </div>

          <Scroller label="Шаги плана по времени">
            <table className="grid">
              <caption>Шаги плана по времени</caption>
              <thead>
                <tr>
                  <th scope="col">Момент</th>
                  <th scope="col">Уставки</th>
                  <th scope="col">Рецепт</th>
                  <th scope="col">Производительность</th>
                </tr>
              </thead>
              <tbody>
                {plan.steps.map((step) => {
                  const stepOrigin = originForStep(step.time_hours);
                  return (
                    <tr key={step.time_hours}>
                      <th scope="row" className="grid__num">
                        {hours(step.time_hours)}
                      </th>
                      <td>
                        {Object.entries(step.controls ?? {}).map(([key, value]) => (
                          <span key={key} className="chip">
                            {controlLabel(key)} <b>{num(value, 1)}</b> {controlUnit(key)}
                            <OriginBadge origin={stepOrigin?.controls[key]} />
                          </span>
                        ))}
                      </td>
                      <td>
                        {Object.entries(step.recipe ?? {}).map(([key, value]) => (
                          <span key={key} className="chip">
                            {names[key] ?? key} <b>{num(value, 3)}</b>
                          </span>
                        ))}
                        {step.recipe && Object.keys(step.recipe).length > 0 ? (
                          <OriginBadge origin={stepOrigin?.recipe} label="рецепт" />
                        ) : null}
                      </td>
                      <td className="grid__num">
                        {num(step.throughput_tph, 1)} т/ч <OriginBadge origin={stepOrigin?.throughput_tph} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Scroller>
        </>
      ) : (
        <Empty>
          {payload.explanation.kind === "agent_rejected"
            ? "План не выбран: допустимый вариант был, но агенты качества/надёжности его отклонили. " +
              "Подробности — на этапе «Агенты» и в панели отказа."
            : "План не выбран, потому что выбирать было не из чего: допустимых вариантов ноль. Сравнение " +
              "планов между собой имеет смысл только после того, как хотя бы один прошёл обязательные проверки."}
        </Empty>
      )}

      <div className="notes-rail">
        {rule ? <Note>{rule}</Note> : null}

        {usesDemand ? (
          <Note>
            В рецепте выбранного плана есть компонент, который нарабатывают по необходимости: разбавление им
            оплачивается более глубокой очисткой, и эта надбавка уже входит в стоимость тонны выше. Ограничением
            служит темп наработки, а не остаток на складе — остатка у этого компонента нет.
          </Note>
        ) : null}
      </div>

      {alternatives.length > 0 ? (
        <Scroller label="Ближайшие альтернативы">
          <table className="grid">
            <caption>
              Почему не они
              <span className="grid__gloss">
                Ближайших альтернатив: {alternatives.length}. Payload несёт не более пяти — это не полный список
                проверенных планов, их число показано на этапе «Кандидаты». Стоимость — в условных единицах
                сценария, не в рублях. В колонке различий перечислены только те уставки и доли рецепта, которые
                отличаются от выбранного плана; совпавшие не печатаются, поэтому пустая колонка значит совпадение,
                а не отсутствие данных. Уставки переданы у {withSetpoints} альтернатив из {alternatives.length};
                сравнение идёт с первым шагом выбранного плана.
              </span>
            </caption>
            <thead>
              <tr>
                <th scope="col">Кандидат</th>
                <th scope="col">Выпуск за горизонт, т</th>
                <th scope="col">Стоимость, у.е./т</th>
                <th scope="col">Тяжесть режима</th>
                <th scope="col">Чем отличается от выбранного</th>
                <th scope="col">Почему не выбран</th>
              </tr>
            </thead>
            <tbody>
              {alternatives.map((item) => (
                <tr key={item.candidate_id}>
                  <th scope="row">
                    <code>{item.candidate_id}</code>
                  </th>
                  <td className="grid__num">{num(item.production_t, 1)}</td>
                  <td className="grid__num">{num(item.cost_per_tonne, 4)}</td>
                  <td className="grid__num">{num(item.severity_index, 3)}</td>
                  <td className="grid__diff">
                    <PlanDiff alternative={item} baseline={baseline} names={names} />
                  </td>
                  <td className="grid__why">{item.why_not}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroller>
      ) : payload.decision.status === "refuse" ? (
        <Empty>
          {payload.explanation.kind === "agent_rejected"
            ? "Списка альтернатив нет: допустимые планы были, но решение не выдано после отклонения агентами " +
              "качества/надёжности. Кто и почему отклонил — на этапе «Агенты»; проверенные варианты — на этапе «Кандидаты»."
            : "Списка альтернатив нет: он строится из допустимых планов, а их не нашлось. Отклонённые варианты " +
              "с причинами отсева показаны на этапе «Кандидаты»."}
        </Empty>
      ) : (
        <Empty>Альтернатив в payload нет.</Empty>
      )}

      {payload.decision.robustness ? (
        <RobustnessMap robustness={payload.decision.robustness} />
      ) : plan ? (
        <Empty>Проверка устойчивости не проводилась или её результат не передавался.</Empty>
      ) : (
        <Empty>
          Устойчивость не проверяли: возмущают выбранный план, а его нет. Пустой блок означает отсутствие
          проверки, а не подтверждённую устойчивость.
        </Empty>
      )}

      {payload.decision.lookahead?.offspec ? (
        <OffspecBlock offspec={payload.decision.lookahead.offspec} />
      ) : null}

      <Fields>
        <Field label="Порядок сравнения">
          {policy?.ranking?.length ? (
            <span className="ranking">
              {policy.ranking.map((key, position) => (
                <span key={key} className="ranking__step">
                  <span className="ranking__order">{position + 1}</span>
                  {rankLabel(key)}
                </span>
              ))}
            </span>
          ) : (
            "правило ранжирования в payload не передавалось"
          )}
        </Field>
        <Field label="Окно уступки по стоимости">
          {isNumber(policy?.severity_cost_tolerance_fraction)
            ? policy.severity_cost_tolerance_fraction === 0
              ? "0 % — уступать стоимостью ради меньшей тяжести режима не разрешено"
              : `${percent(policy.severity_cost_tolerance_fraction)} — в этих пределах выбирается менее тяжёлый режим`
            : "не передавалось"}
        </Field>
        <Field label="Потолок тяжести режима">
          {isNumber(policy?.max_severity_index)
            ? `${num(policy.max_severity_index, 3)} — планы тяжелее этого порога до сравнения не допускаются`
            : policy
              ? "не задан: тяжесть режима сверху не ограничивали"
              : "не передавалось"}
        </Field>
        <Field label="Проекция за горизонт">
          {payload.decision.lookahead?.available
            ? `${hours(payload.decision.lookahead.lookahead_hours)}; смена плана: ${
                payload.decision.lookahead.switched ? "да" : "не потребовалась"
              }`
            : plan
              ? "недоступна: сервер не передал проекцию за горизонт"
              : "не строилась: проецировать нечего, плана нет"}
        </Field>
        <Field label="Устойчивость">
          {payload.decision.robustness ? (
            <>
              выдержал {payload.decision.robustness.held} из {payload.decision.robustness.perturbations_evaluated}{" "}
              возмущений
              {payload.decision.robustness.fragile ? <Tag tone="unknown">чувствителен</Tag> : <Tag tone="pass">держится</Tag>}
            </>
          ) : plan ? (
            "не проверялась: результат проверки устойчивости не передавался"
          ) : (
            "не проверялась: возмущать нечего, плана нет"
          )}
        </Field>
      </Fields>

      <JsonPanel
        title="JSON: выбор, альтернативы, устойчивость, проекция"
        value={{
          selected_plan: plan,
          alternatives,
          comparison_rule: rule,
          selection_policy: policy,
          robustness: payload.decision.robustness,
          lookahead: payload.decision.lookahead
        }}
      />
    </Section>
  );
}
