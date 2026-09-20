export const TRUNCATION_MARK = "…";

const LIMIT_TEXT: Record<string, string> = {
  sulfur_mgkg: "сера",
  t95_c: "T95",
  cetane_number: "цетановое число",
  density_max_kgm3: "плотность",
  density_min_kgm3: "плотность снизу",
  flash_point_c: "температура вспышки",
  cfpp_c: "предельная температура фильтруемости"
};

const RANK_KEY_TEXT: Record<string, string> = {
  "-production_t": "больше выпуска",
  production_t: "меньше выпуска",
  cost_per_tonne: "дешевле за тонну",
  "-cost_per_tonne": "дороже за тонну",
  severity_index: "спокойнее режим",
  "-severity_index": "тяжелее режим",
  changes: "меньше переключений",
  "-changes": "больше переключений",
  candidate_id: "по идентификатору плана"
};

export function limitText(key: string): string {
  return LIMIT_TEXT[key] ?? key;
}

// Независимая проверка (второй заход): decision.reason иногда приходит от детерминированного backend
// (lookahead.py: "Упреждение за горизонтом: при плане {id} {constraint} = {value} при пределе {limit}
// …") с сырым именем свойства качества внутри обычной русской фразы. Backend — не текстовый шаблон,
// который стоит трогать здесь (влияет на decision_id и замороженные хеши тестов), поэтому подставляем
// перевод уже готовой фразы на фронтенде: находим известные ключи как целые слова и меняем на текст
// из того же словаря LIMIT_TEXT, которым уже переведены margin/constraint UI в других местах.
const QUALITY_KEY_PATTERN = new RegExp(
  `\\b(${Object.keys(LIMIT_TEXT).map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`,
  "g"
);

export function humanizeReason(text: string): string {
  return text.replace(QUALITY_KEY_PATTERN, (match) => LIMIT_TEXT[match] ?? match);
}

// Полный словарь proposed_constraints.type — см. CONSTRAINT_VOCABULARY в
// application/agentic/specialist.py. Независимая проверка нашла, что constraintText() переводит
// только .limit (сера/цетан/…), а сам .type оставался сырым кодом на основном экране.
const TYPE_TEXT: Record<string, string> = {
  min_quality_margin: "минимальный запас качества",
  max_changes: "не более переключений",
  forbid_additive: "запрет присадки",
  max_outflow_utilization: "предел загрузки по расходу",
  constant_plans_only: "только постоянный режим",
  min_hours_to_violation: "минимум часов до нарушения",
  require_not_fragile: "план должен быть устойчивым"
};

export function constraintTypeText(type: string): string {
  return TYPE_TEXT[type] ?? type;
}

export function rankKeyText(key: string): string {
  return RANK_KEY_TEXT[key] ?? key;
}

export function parseObject(raw: string | undefined): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as unknown;
    if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
    return value as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function numberAt(source: Record<string, unknown> | null, key: string): number | null {
  const value = source?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function stringAt(source: Record<string, unknown> | null, key: string): string | null {
  const value = source?.[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function boolAt(source: Record<string, unknown> | null, key: string): boolean | null {
  const value = source?.[key];
  return typeof value === "boolean" ? value : null;
}

export function stringsAt(source: Record<string, unknown> | null, key: string): string[] | null {
  const value = source?.[key];
  if (!Array.isArray(value)) return null;
  return value.map((item) => String(item));
}

export function objectsAt(source: Record<string, unknown> | null,
  key: string): Array<Record<string, unknown>> | null {
  const value = source?.[key];
  if (!Array.isArray(value)) return null;
  const out: Array<Record<string, unknown>> = [];
  for (const item of value) {
    if (item !== null && typeof item === "object" && !Array.isArray(item)) {
      out.push(item as Record<string, unknown>);
    }
  }
  return out;
}

export function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return many;
  const last = count % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function decimal(value: number, digits: number): string {
  return value.toFixed(digits).replace(".", ",");
}

export function constraintText(item: Record<string, unknown>): string {
  const rawType = stringAt(item, "type");
  const type = rawType ? constraintTypeText(rawType) : "ограничение без типа";
  const limit = stringAt(item, "limit");
  const value = numberAt(item, "value");
  const parts: string[] = [type];
  if (limit !== null) parts.push(limitText(limit));
  if (value !== null) parts.push(decimal(value, 3));
  return parts.join(" · ");
}

export function salvage(raw: string | undefined): Record<string, unknown> | null {
  if (!raw || !raw.endsWith(TRUNCATION_MARK)) return null;
  const body = raw.slice(0, -TRUNCATION_MARK.length);
  if (!body.startsWith("{")) return null;
  const out: Record<string, unknown> = {};
  const scalar = /"([A-Za-z0-9_]+)":(-?\d+(?:\.\d+)?|true|false|null)(?=[,}])/g;
  for (;;) {
    const hit = scalar.exec(body);
    if (hit === null) break;
    const key = hit[1];
    const text = hit[2];
    if (key === undefined || text === undefined) continue;
    if (text === "true") out[key] = true;
    else if (text === "false") out[key] = false;
    else if (text === "null") out[key] = null;
    else out[key] = Number(text);
  }
  return Object.keys(out).length > 0 ? out : null;
}
