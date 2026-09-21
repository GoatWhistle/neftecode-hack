import { additiveDoseKgPerT, controlLabel, controlUnit, doseDigits, isNumber, num } from "../format";
import type { Alternative, PlanStep } from "../types";

export interface DiffEntry {
  key: string;
  label: string;
  unit: string;
  from: number;
  to: number;
  digits: number;
}

export interface PlanDiffProps {
  alternative: Alternative;
  baseline: PlanStep | null;
  names: Record<string, string>;
}

function delta(value: number, digits: number): string {
  const text = num(Math.abs(value), digits);
  return `${value > 0 ? "+" : "−"}${text}`;
}

function collect(
  base: Record<string, number> | undefined,
  other: Record<string, number> | undefined,
  label: (key: string) => string,
  unit: (key: string) => string,
  digits: number,
  prefix: string
): DiffEntry[] {
  const keys = new Set([...Object.keys(base ?? {}), ...Object.keys(other ?? {})]);
  const out: DiffEntry[] = [];
  for (const key of [...keys].sort()) {
    const from = base?.[key];
    const to = other?.[key];
    if (!isNumber(from) || !isNumber(to)) continue;
    if (Number(from.toFixed(digits)) === Number(to.toFixed(digits))) continue;
    out.push({ key: `${prefix}${key}`, label: label(key), unit: unit(key), from, to, digits });
  }
  return out;
}

export function planDiff(alternative: Alternative, baseline: PlanStep | null, names: Record<string, string>): DiffEntry[] {
  if (!baseline) return [];
  const entries = [
    ...collect(baseline.controls, alternative.controls, controlLabel, controlUnit, 1, "c."),
    ...collect(
      baseline.recipe,
      alternative.recipe,
      (key) => names[key] ?? key,
      () => "доля",
      3,
      "r."
    )
  ];
  if (
    isNumber(baseline.throughput_tph) &&
    isNumber(alternative.throughput_tph) &&
    Number(baseline.throughput_tph.toFixed(1)) !== Number(alternative.throughput_tph.toFixed(1))
  ) {
    entries.push({
      key: "throughput",
      label: "Производительность",
      unit: "т/ч",
      from: baseline.throughput_tph,
      to: alternative.throughput_tph,
      digits: 1
    });
  }
  if (
    isNumber(baseline.additive_dose) &&
    isNumber(alternative.additive_dose) &&
    Number(baseline.additive_dose.toFixed(3)) !== Number(alternative.additive_dose.toFixed(3))
  ) {
    const fromKg = additiveDoseKgPerT(baseline.additive_dose)!;
    const toKg = additiveDoseKgPerT(alternative.additive_dose)!;
    entries.push({
      key: "additive",
      label: "Доза присадки",
      unit: "кг/т",
      from: fromKg,
      to: toKg,
      digits: Math.max(doseDigits(fromKg), doseDigits(toKg), doseDigits(toKg - fromKg))
    });
  }
  return entries;
}

export function PlanDiff({ alternative, baseline, names }: PlanDiffProps) {
  if (!alternative.controls && !alternative.recipe) {
    return <span className="diff__none">уставки этого кандидата в payload не передавались</span>;
  }
  if (!baseline) {
    return <span className="diff__none">сравнивать не с чем: уставок выбранного плана в payload нет</span>;
  }
  const entries = planDiff(alternative, baseline, names);
  if (entries.length === 0) {
    return <span className="diff__same">уставки и рецепт совпадают с выбранным планом</span>;
  }
  return (
    <span className="diff">
      {entries.map((entry) => (
        <span key={entry.key} className="diff__chip">
          <span className="diff__label">{entry.label}</span>
          <b className="diff__delta">{delta(entry.to - entry.from, entry.digits)}</b>
          {entry.unit ? <span className="diff__unit">{entry.unit}</span> : null}
          <span className="diff__pair">
            {num(entry.from, entry.digits)} → {num(entry.to, entry.digits)}
          </span>
        </span>
      ))}
    </span>
  );
}
