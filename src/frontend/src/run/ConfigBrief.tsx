import type { Conditions, RunOptions, TankOption } from "./options";
import { FAULT_LABELS } from "./options";

export interface ConfigBriefProps {
  options: RunOptions;
  conditions: Conditions;
  tank: TankOption | null;
  folded?: boolean;
}

interface Line {
  term: string;
  value: string;
}

function snapshotTitle(options: RunOptions, key: string): string {
  return options.snapshots.find((item) => item.key === key)?.title ?? key;
}

export function ConfigBrief({ options, conditions, tank, folded }: ConfigBriefProps) {
  const lines: Line[] = [
    { term: "Сценарий", value: conditions.scenario },
    { term: "Момент", value: snapshotTitle(options, conditions.snapshot) },
    { term: "Источники", value: FAULT_LABELS[conditions.fault] ?? conditions.fault }
  ];

  if (tank) {
    lines.push({
      term: "Резервуар",
      value: tank.on_demand
        ? `${tank.id} — нарабатывают по необходимости`
        : `${tank.id} — ${conditions.tank_available === "1" ? "в работе" : "выведен"}`
    });
  }

  const id = folded ? "brief-folded-title" : "brief-title";

  return (
    <aside className={`brief ${folded ? "brief--folded" : ""}`} aria-labelledby={id}>
      <h3 className="brief__title" id={id}>
        {folded ? "Ушло на расчёт" : "Что уйдёт на расчёт"}
      </h3>
      <dl className="brief__list">
        {lines.map((line) => (
          <div className="brief__line" key={line.term}>
            <dt className="brief__term">{line.term}</dt>
            <dd className="brief__value">{line.value}</dd>
          </div>
        ))}
      </dl>
      {folded ? null : (
        <>
          <p className="brief__note">
            Сервер получает ровно эти условия. Числа пределов и производительности берутся из полей
            слева как есть — интерфейс их не пересчитывает.
          </p>
          <p className="brief__note">
            Сервер предлагает {options.scenarios.length} сценариев и {options.faults.length}{" "}
            вариантов отказа источников; выбран один из них. Прогон считается по нему целиком.
          </p>
        </>
      )}
    </aside>
  );
}
