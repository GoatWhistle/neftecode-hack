import type { Conditions, TankOption } from "./options";

export interface NumberFieldProps {
  label: string;
  value: string;
  step: string;
  disabled: boolean;
  onChange: (value: string) => void;
}

export function NumberField({ label, value, step, disabled, onChange }: NumberFieldProps) {
  if (value === "") return null;
  return (
    <label className="config__field">
      <span>{label}</span>
      <input type="number" step={step} value={value} disabled={disabled}
        onChange={(event) => onChange(event.target.value)} />
    </label>
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
      <label className="config__field">
        <span>Резервуар</span>
        <select value={conditions.tank} disabled={disabled} onChange={(event) => pick(event.target.value)}>
          {tanks.map((item) => (
            <option key={item.id} value={item.id}>{item.id}</option>
          ))}
        </select>
      </label>

      {tank?.on_demand ? (
        <p className="config__hint">
          Компонент <code>{tank.id}</code> нарабатывают по необходимости: запаса на складе у него нет,
          менять нечего.
        </p>
      ) : (
        <label className="config__field">
          <span>Запас резервуара, т</span>
          <input type="number" step="10" value={conditions.tank_inventory} disabled={disabled}
            onChange={(event) => onChange({ tank_inventory: event.target.value })} />
        </label>
      )}

      <label className="config__field">
        <span>Доступность резервуара</span>
        <select value={conditions.tank_available} disabled={disabled}
          onChange={(event) => onChange({ tank_available: event.target.value })}>
          <option value="1">в работе</option>
          <option value="0">выведен</option>
        </select>
      </label>
    </>
  );
}
