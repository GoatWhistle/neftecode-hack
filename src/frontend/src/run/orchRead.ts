export const TRUNCATION_MARK = "…";

// Человеческие подписи для известных синтетических демо-сценариев (config/scenarios, шесть штук из
// state.md). Живые сценарии (реальный момент времени) под этот словарь не попадают и показываются
// как есть — это не внутренний код, а конкретный идентификатор запуска. Используется и в форме
// выбора сценария (ConfigStage), и в отображении принятого решения (StateStage) — раньше форма
// показывала сырые id ("ample_reserve"), а StateStage уже был переведён.
export const SCENARIO_LABEL: Record<string, string> = {
  baseline: "норма",
  ample_reserve: "запас по резерву",
  light_component: "лёгкий компонент",
  no_feasible: "нет допустимого плана",
  sour_crude: "сернистое сырьё",
  winter_grade: "зимняя марка"
};

export function scenarioLabel(id: string | null): string {
  if (!id) return "—";
  return SCENARIO_LABEL[id] ?? id;
}

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

// legacy_status / decision.status — три кода из domain/shared/primitives.py (HOLD,
// RECOMMEND_SCENARIO, REFUSE). Тот же candidate_id "hold" backend использует и как id плана внутри
// lookahead.py, поэтому словарь переиспользуется humanizeReason() ниже, а не только AgenticMode.tsx.
export const STATUS_TEXT: Record<string, string> = {
  hold: "сохранить режим",
  recommend_scenario: "изменить режим",
  refuse: "отказ"
};

// Независимая проверка (второй и третий заход): decision.reason иногда приходит от детерминированного
// backend (lookahead.py: "Упреждение за горизонтом: при плане {id} {constraint} = {value} при пределе
// {limit} …") с сырым именем свойства качества и/или id плана (может совпадать с кодом статуса,
// например "hold") внутри обычной русской фразы. Backend — не текстовый шаблон, который стоит трогать
// здесь (влияет на decision_id и замороженные хеши тестов), поэтому подставляем перевод уже готовой
// фразы на фронтенде: находим известные ключи как целые слова и меняем на текст из тех же словарей,
// которыми уже переведены margin/constraint/статус в других местах интерфейса.
const HUMANIZE_MAP: Record<string, string> = { ...LIMIT_TEXT, ...STATUS_TEXT };
const HUMANIZE_PATTERN = new RegExp(
  `\\b(${Object.keys(HUMANIZE_MAP).map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`,
  "g"
);

export function humanizeReason(text: string): string {
  return text.replace(HUMANIZE_PATTERN, (match) => HUMANIZE_MAP[match] ?? match);
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
