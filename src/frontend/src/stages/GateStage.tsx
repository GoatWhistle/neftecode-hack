import type { CheckStatus, GateCheck } from "../types";
import { familyOf, hours, num } from "../format";
import { Empty, Field, Fields, LampDot, Note, Readout, Scroller } from "../ui/Primitives";
import { Section } from "../ui/Section";
import { JsonPanel } from "../ui/Json";
import { GateMatrix } from "../ui/GateMatrix";
import { HeadroomBars } from "../ui/HeadroomBars";
import type { StageProps } from "./StateStage";

interface FamilyRow {
  family: string;
  pass: number;
  fail: number;
  unknown: number;
}

function byFamily(checks: GateCheck[]): FamilyRow[] {
  const map = new Map<string, FamilyRow>();
  for (const check of checks) {
    const family = familyOf(check.constraint_id);
    const row = map.get(family) ?? { family, pass: 0, fail: 0, unknown: 0 };
    row[check.status] += 1;
    map.set(family, row);
  }
  return [...map.values()].sort((a, b) => b.fail - a.fail || b.unknown - a.unknown || a.family.localeCompare(b.family));
}

function count(checks: GateCheck[], status: CheckStatus): number {
  return checks.filter((check) => check.status === status).length;
}

export function GateStage({ payload, index, state, source, lamp, lampTitle, bare }: StageProps) {
  const gate = payload.decision.gate;
  const checks = gate?.checks ?? [];
  const failed = checks.filter((check) => check.status === "fail");
  const unknown = checks.filter((check) => check.status === "unknown");
  const broken = [...failed, ...unknown];
  const shownBroken = broken.slice(0, 25);
  const families = byFamily(checks);

  return (
    <Section
      id="gate"
      index={index}
      state={state}
      source={source}
      title="Gate"
      lead="Жёсткая проверка выбранного плана: каждое ограничение в каждый момент горизонта."
      lamp={lamp}
      lampTitle={lampTitle}
      bare={bare}
    >
      {checks.length === 0 ? (
        payload.decision.status === "refuse" ? (
          <Empty>
            {payload.explanation.kind === "agent_rejected"
              ? "Отдельного протокола Gate здесь нет: жёсткие проверки допустимый план прошёл (см. этап " +
                "«Кандидаты»), но до финальной перепроверки дело не дошло — агенты качества/надёжности " +
                "отклонили его раньше. Подробности — на этапе «Агенты»."
              : "Отдельного протокола Gate здесь нет, и это не пропуск: проверять было нечего — ни один план " +
                "не дожил до финальной проверки. Что именно отсеяло варианты, показано на этапе «Решение» и в " +
                "трассе оптимизатора на этапе «Кандидаты»."}
          </Empty>
        ) : (
          <Empty>Проверки Gate не передавались.</Empty>
        )
      ) : (
        <>
          <div className="readouts">
            <Readout label="Проверок всего" value={String(checks.length)} hint={`план ${gate?.plan_id ?? "—"}`} />
            <Readout label="Пройдено" value={String(count(checks, "pass"))} tone="pass" />
            <Readout
              label="Нарушено"
              value={String(failed.length)}
              tone={failed.length > 0 ? "fail" : "pass"}
            />
            <Readout
              label="Неизвестно"
              value={String(unknown.length)}
              tone={unknown.length > 0 ? "unknown" : "pass"}
              hint="нет данных для проверки"
            />
          </div>

          <Scroller label="Матрица проверок Gate">
            <GateMatrix checks={checks} />
          </Scroller>

          <HeadroomBars checks={checks} names={payload.explanation.component_names ?? {}} />

          <Scroller label="Проверки по семействам ограничений">
            <table className="grid">
              <caption>Проверки по семействам ограничений</caption>
              <thead>
                <tr>
                  <th scope="col">Семейство</th>
                  <th scope="col">Пройдено</th>
                  <th scope="col">Нарушено</th>
                  <th scope="col">Неизвестно</th>
                </tr>
              </thead>
              <tbody>
                {families.map((row) => (
                  <tr key={row.family}>
                    <th scope="row">
                      <LampDot state={row.fail > 0 ? "fail" : row.unknown > 0 ? "unknown" : "pass"} />
                      {row.family}
                    </th>
                    <td className="grid__num">{row.pass}</td>
                    <td className="grid__num">{row.fail}</td>
                    <td className="grid__num">{row.unknown}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>

          {broken.length > 0 ? (
            <Scroller label="Что именно не прошло">
              <table className="grid">
                <caption>Что именно не прошло</caption>
                <thead>
                  <tr>
                    <th scope="col">Ограничение</th>
                    <th scope="col">Наблюдалось</th>
                    <th scope="col">Предел</th>
                    <th scope="col">Момент</th>
                    <th scope="col">Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {shownBroken.map((check, position) => (
                    <tr key={`${check.constraint_id}-${check.time_hours}-${position}`}>
                      <th scope="row">
                        <LampDot state={check.status === "fail" ? "fail" : "unknown"} />
                        <code>{check.constraint_id}</code>
                      </th>
                      <td className="grid__num">{num(check.observed, 3)}</td>
                      <td className="grid__num">{num(check.limit, 3)}</td>
                      <td className="grid__num">{hours(check.time_hours)}</td>
                      <td>{check.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroller>
          ) : null}

          <div className="notes-rail">
            {broken.length === 0 ? (
              <Note>Ни одно жёсткое ограничение не нарушено и ни одно не осталось непроверенным.</Note>
            ) : null}

            {broken.length > shownBroken.length ? (
              <Note>
                Показаны первые {shownBroken.length} из {broken.length}; остальные — в JSON ниже.
              </Note>
            ) : null}
          </div>

          <Fields>
            <Field label="План допустим">{gate?.feasible ? "да" : "нет"}</Field>
            <Field label="Первое нарушение">
              {gate?.first_violation ? <code>{gate.first_violation.constraint_id}</code> : "нет"}
            </Field>
            <Field label="Непроверенные требования">
              {gate?.unknown_requirements?.length ? gate.unknown_requirements.join("; ") : "нет"}
            </Field>
          </Fields>
        </>
      )}

      <JsonPanel title={`JSON: Gate. Проверок: ${checks.length}`} value={gate} />
    </Section>
  );
}
