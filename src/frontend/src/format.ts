const CONTROL_LABELS: Record<string, string> = {
  avt_furnace_outlet_temp_c: "Температура на выходе печи АВТ",
  crude_feed_rate_tph: "Расход сырья на АВТ",
  ht_reactor_inlet_temp_c: "Температура на входе реактора ГО",
  ht_feed_flow_m3h: "Расход сырья гидроочистки"
};

const CONTROL_UNITS: Record<string, string> = {
  avt_furnace_outlet_temp_c: "°C",
  crude_feed_rate_tph: "т/ч",
  ht_reactor_inlet_temp_c: "°C",
  ht_feed_flow_m3h: "м³/ч"
};

const FAMILY_LABELS: Record<string, string> = {
  quality: "Качество",
  inventory: "Запасы",
  outflow: "Отгрузка",
  control: "Уставки",
  additive: "Присадка",
  plan: "План",
  recipe: "Рецепт",
  throughput: "Производительность",
  model: "Применимость модели"
};

const TERM_LABELS: Record<string, string> = {
  temperature_above_reference: "Превышение температуры над опорной",
  throughput_above_reference: "Превышение расхода над опорным"
};

const ORIGIN_LABELS: Record<string, string> = {
  given: "выдано организаторами",
  derived: "наш расчёт",
  scenario: "задано сценарием",
  measured: "измерение",
  open: "не определено"
};

export const MISSING = "не передавалось";

export function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function num(value: unknown, digits = 3): string {
  if (!isNumber(value)) return "—";
  const rounded = Number(value.toFixed(digits));
  return rounded.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}

export function withUnit(value: unknown, unit: string, digits = 3): string {
  const text = num(value, digits);
  return text === "—" ? text : `${text} ${unit}`;
}

export function percent(value: unknown, digits = 1): string {
  if (!isNumber(value)) return "—";
  return `${num(value * 100, digits)} %`;
}

export function hours(value: unknown): string {
  if (!isNumber(value)) return "—";
  return `${num(value, 2)} ч`;
}

export function controlLabel(key: string): string {
  return CONTROL_LABELS[key] ?? key;
}

export function controlUnit(key: string): string {
  return CONTROL_UNITS[key] ?? "";
}

export function familyOf(constraintId: string): string {
  const head = constraintId.split(".")[0] ?? constraintId;
  return FAMILY_LABELS[head] ?? head;
}

export function termLabel(key: string): string {
  return TERM_LABELS[key] ?? key;
}

export function originLabel(key: string | null | undefined): string {
  if (!key) return MISSING;
  return ORIGIN_LABELS[key] ?? key;
}

export function moment(value: string | null): string {
  if (!value) return MISSING;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

export function duration(ms: number | undefined): string {
  if (ms === undefined || !Number.isFinite(ms)) return "—";
  const total = Math.max(0, ms);
  const minutes = Math.floor(total / 60000);
  const rest = total - minutes * 60000;
  const seconds = Math.floor(rest / 1000);
  const tenth = Math.floor((rest - seconds * 1000) / 100);
  if (minutes === 0) return `${seconds},${tenth}`;
  return `${minutes}:${String(seconds).padStart(2, "0")},${tenth}`;
}

export function spanText(ms: number | undefined): string {
  if (ms === undefined || !Number.isFinite(ms)) return "—";
  return ms < 100 ? "<0,1" : duration(ms);
}
