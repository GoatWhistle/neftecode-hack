import type { ScreenPayload } from "../types";
import { controlLabel, controlUnit, doseText, isNumber, num } from "../format";

export type ChangeKind = "control" | "recipe" | "throughput" | "additive";

export interface ChangeLine {
  kind: ChangeKind;
  key: string;
  label: string;
  from: string;
  to: string;
}

interface OperationLike {
  controls?: Record<string, number>;
  recipe?: Record<string, number>;
  throughput_tph?: number | null;
  additive_dose?: number | null;
}

function same(a: number, b: number, digits: number): boolean {
  return Number(a.toFixed(digits)) === Number(b.toFixed(digits));
}

export function currentOperationOf(payload: ScreenPayload): OperationLike | null {
  return payload.explanation?.current_operation ?? payload.decision.current_operation ?? null;
}

/** Параметры, которые предложенное действие меняет относительно текущего режима: было → предложено. */
export function changeLines(payload: ScreenPayload): ChangeLine[] | null {
  const action = payload.decision.immediate_action;
  const current = currentOperationOf(payload);
  if (!action || !current) return null;
  const names = payload.explanation?.component_names ?? {};
  const lines: ChangeLine[] = [];
  const controlKeys = new Set([...Object.keys(current.controls ?? {}), ...Object.keys(action.controls ?? {})]);
  for (const key of [...controlKeys].sort()) {
    const from = current.controls?.[key];
    const to = action.controls?.[key];
    if (!isNumber(from) || !isNumber(to) || same(from, to, 1)) continue;
    const unit = controlUnit(key);
    lines.push({ kind: "control", key, label: controlLabel(key), from: `${num(from, 1)} ${unit}`.trim(),
      to: `${num(to, 1)} ${unit}`.trim() });
  }
  const recipeKeys = new Set([...Object.keys(current.recipe ?? {}), ...Object.keys(action.recipe ?? {})]);
  for (const key of [...recipeKeys].sort()) {
    const from = current.recipe?.[key];
    const to = action.recipe?.[key];
    if (!isNumber(from) || !isNumber(to) || same(from, to, 3)) continue;
    lines.push({ kind: "recipe", key, label: `Доля ${names[key] ?? key}, % масс.`, from: num(from * 100, 1),
      to: num(to * 100, 1) });
  }
  if (isNumber(current.throughput_tph) && isNumber(action.throughput_tph) && !same(current.throughput_tph, action.throughput_tph, 1)) {
    lines.push({ kind: "throughput", key: "throughput_tph", label: "Производительность",
      from: `${num(current.throughput_tph, 1)} т/ч`, to: `${num(action.throughput_tph, 1)} т/ч` });
  }
  const doseFrom = current.additive_dose;
  const doseTo = action.additive_dose;
  if (isNumber(doseFrom) && isNumber(doseTo) && !same(doseFrom, doseTo, 6)) {
    lines.push({ kind: "additive", key: "additive_dose", label: "Доза присадки", from: doseText(doseFrom),
      to: doseText(doseTo) });
  }
  return lines;
}

export function changeText(line: ChangeLine): string {
  return `${line.label}: ${line.from} → ${line.to}`;
}
