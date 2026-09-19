import { useId } from "react";
import type { Conditions, TankOption } from "./options";
import { Select } from "../ui/Select";

export interface NumberFieldProps {
  label: string;
  unit?: string;
  value: string;
  step: string;
  disabled: boolean;
  onChange: (value: string) => void;
}

export function NumberField({ label, unit, value, step, disabled, onChange }: NumberFieldProps) {
  const id = useId();
  if (value === "") {
    return (
      <p className="ctl ctl--missing">
        <span className="ctl__label">{label}</span>
        <span className="ctl__absent">сервер значения не передал, менять нечего</span>
      </p>
    );
  }
  return (
    <div className="ctl">
      <label className="ctl__label" htmlFor={id}>
        {label}
      </label>
      <div className="ctl__wrap">
        <input id={id} className="ctl__control ctl__control--number" type="number" step={step}
          value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
        {unit ? <span className="ctl__unit" aria-hidden="true">{unit}</span> : null}
      </div>
    </div>
  );
}

export interface TankFieldProps {
  conditions: Conditions;
  tanks: TankOption[];
  tank: TankOption | null;
  disabled: boolean;
  onChange: (patch: Partial<Conditions>) => void;
}

export function TankField({ conditions, tanks, tank, disabled, onChange }: TankFieldProps) {
  if (tanks.length === 0) return null;

  const pick = (id: string): void => {
    const next = tanks.find((item) => item.id === id) ?? null;
    onChange({
      tank: id,
      tank_inventory: next?.inventory === null || next?.inventory === undefined ? "" : String(next.inventory),
      tank_available: next ? (next.available ? "1" : "0") : ""
    });
  };

  return (
    <>
      <Select label="Резервуар" value={conditions.tank} disabled={disabled} onChange={pick}
        options={tanks.map((item) => ({ value: item.id, label: item.id }))} />

      {tank?.on_demand ? (
        <p className="ctl ctl--missing">
          <span className="ctl__label">Запас резервуара</span>
          <span className="ctl__absent">
            <code>{tank.id}</code> нарабатывают по необходимости: запаса на складе нет
          </span>
        </p>
      ) : (
        <NumberField label="Запас резервуара" unit="т" step="10" value={conditions.tank_inventory}
          disabled={disabled} onChange={(value) => onChange({ tank_inventory: value })} />
      )}

      <Select label="Доступность резервуара" value={conditions.tank_available} disabled={disabled}
        onChange={(value) => onChange({ tank_available: value })}
        options={[
          { value: "1", label: "в работе" },
          { value: "0", label: "выведен" }
        ]} />
    </>
  );
}
