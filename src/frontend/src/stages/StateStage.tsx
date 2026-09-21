import type { StageState } from "../run/types";
import type { ScreenPayload } from "../types";
import type { Lamp } from "../ui/Primitives";
import { additiveDoseKgPerT, controlLabel, controlUnit, doseDigits, moment, num, withUnit } from "../format";
import { Empty, Field, Fields, Note, Readout, Scroller } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { OriginBadge, OriginLegend } from "../ui/Origin";
import { onDemandIds, stockLine, tanksOf } from "../provenance";
import { SCENARIO_LABEL, scenarioLabel } from "../run/orchRead";

export interface StageProps {
  payload: ScreenPayload;
  index: number;
  state?: StageState | undefined;
  source?: string | undefined;
  lamp: Lamp;
  lampTitle: string;
  bare?: boolean | undefined;
}

export function StateStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const operation = payload.explanation.current_operation ?? payload.decision.current_operation;
  const origin = payload.explanation.current_operation?.origin ?? null;
  const names = payload.explanation.component_names ?? {};
  const inventories = payload.inventories ?? {};
  const tanks = tanksOf(payload);
  const demand = onDemandIds(payload);
  const doseKg = operation ? additiveDoseKgPerT(operation.additive_dose) : null;
  const chainBlocks = payload.explanation.chain?.blocks ?? [];
  const controllableOf = (key: string): boolean | null => {
    for (const block of chainBlocks) {
      if (key in block.controls) return block.controls[key] ?? null;
    }
    return null;
  };
  const NOT_MOVED_HINT = "не двигается советчиком в текущем режиме";

  return (
    <Section
      id="state"
      index={index}
      state={state}
      source={source}
      title="Состояние"
      lead="Режим на момент решения: уставки, рецепт смешения, запасы компонентов."
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      <Fields>
        <Field label="Момент решения">{moment(payload.decision_time)}</Field>
        <Field label="Происхождение состояния">{payload.state_origin ?? "не указано"}</Field>
        <Field label="Сценарий">
          {scenarioLabel(payload.decision.scenario_id)}
          {payload.decision.scenario_id && SCENARIO_LABEL[payload.decision.scenario_id] ? (
            <> (<code>{payload.decision.scenario_id}</code>)</>
          ) : null}
        </Field>
        <Field label="Идентификатор решения">
          <code>{payload.decision.decision_id ?? "—"}</code>
        </Field>
      </Fields>

      {operation ? (
        <>
          <OriginLegend />
          <div className="readouts">
            {Object.entries(operation.controls ?? {}).map(([key, value]) => (
              <Readout
                key={key}
                label={controlLabel(key)}
                value={num(value, 2)}
                unit={controlUnit(key)}
                badge={<OriginBadge origin={origin?.controls?.[key]} />}
                hint={controllableOf(key) === false ? NOT_MOVED_HINT : undefined}
              />
            ))}
            <Readout
              label="Производительность"
              value={num(operation.throughput_tph, 2)}
              unit="т/ч"
              badge={<OriginBadge origin={origin?.throughput_tph} />}
              hint={controllableOf("throughput_tph") === false ? NOT_MOVED_HINT : undefined}
            />
            <Readout
              label="Доза присадки"
              value={doseKg === null ? "—" : num(doseKg, doseDigits(doseKg))}
              unit="кг/т"
              badge={<OriginBadge origin={origin?.additive_dose} />}
              hint={controllableOf("additive_dose") === false ? NOT_MOVED_HINT : undefined}
            />
          </div>
          <Scroller label="Рецепт смешения и запасы">
            <table className="grid">
              <caption>
                Рецепт смешения и запасы <OriginBadge origin={origin?.recipe} label="рецепт" />
                <span className="grid__gloss">
                  Доли рецепта и остаток каждого компонента на момент решения.
                </span>
              </caption>
              <thead>
                <tr>
                  <th scope="col">Компонент</th>
                  <th scope="col">Доля в смеси</th>
                  <th scope="col">Остаток на момент решения</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys({ ...names, ...operation.recipe, ...inventories }).map((key) => {
                  const line = stockLine(payload, key);
                  return (
                    <tr key={key}>
                      <th scope="row">{names[key] ?? key}</th>
                      <td className="grid__num">{withUnit(operation.recipe?.[key], "", 3)}</td>
                      <td>
                        <span className={`stock ${line.onDemand ? "stock--demand" : ""}`}>
                          <OriginBadge origin={line.origin} />
                          {line.text}
                        </span>
                        <span className="stock__hint">{line.hint}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Scroller>

          <div className="notes-rail">
            {demand.length > 0 ? (
              <Note>
                Компонент «{names[demand[0] as string] ?? demand[0]}» на складе не хранится: поле запаса у него
                пустое не потому, что склад опустел, а потому, что запаса у него не бывает. Его нарабатывают под
                заявку, и ограничением служит темп наработки, а не остаток. Разбавление этим компонентом
                оплачивается более глубокой очисткой — она дороже тонны основного потока, и эта разница входит в
                стоимость тонны на этапе «Выбор».
              </Note>
            ) : null}

            {tanks.some((tank) => tank.available === false) ? (
              <Note tone="warn">
                Компоненты, помеченные «выведен из работы», исключены условиями сценария: в смешение они не идут
                независимо от остатка.
              </Note>
            ) : null}
          </div>
        </>
      ) : (
        <Empty>Текущий режим в решении не передавался.</Empty>
      )}

      <JsonPanel
        title="JSON: текущий режим и запасы"
        value={{ current_operation: operation, inventories, tanks }}
      />
    </Section>
  );
}
