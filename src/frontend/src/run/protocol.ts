import type { ScreenPayload } from "../types";
import type { ResearchSummary } from "../features/evidence-passport/research";
import { researchSlot, ResearchSummaryError } from "../features/evidence-passport/research";
import type { RecordedFrame, RunRecord } from "./record";
import { RECORD_SCHEMA } from "./record";
import { sha256Hex } from "./sha256";
import { canonicalJson } from "./canonical";
import { comparePair } from "./pair";
import { hydrateRun, recordInfoOf } from "./hydrate";
import type { Check } from "./recordShape";
import { FORM_FIELDS, formShape, nullable, payloadShape, runMetaShape, ShapeError } from "./recordShape";

export const PROTOCOL_FORMAT = "neftecode.decision-protocol";
export const PROTOCOL_VERSION = 1;
export const MAX_PROTOCOL_BYTES = 8 * 1024 * 1024;

const PAYLOAD_FIELDS = [
  "state", "title", "status_label", "decision", "explanation", "inventories", "sources", "rule_origin",
  "state_origin", "decision_time", "forecast", "forecast_used", "defaults", "applied", "injection", "snapshot",
  "binding", "run_meta", "decision_timeout_s", "agentic_state", "history"
] as const;

export { canonicalJson };

export class ProtocolError extends Error {}

export interface ProtocolContent {
  a: RunRecord | null;
  b: RunRecord | null;
  differences: unknown;
  /** Сводка исследования, с которой показан паспорт; в старых пакетах поля нет. */
  research?: ResearchSummary | null;
}

export interface Protocol {
  format: typeof PROTOCOL_FORMAT;
  version: number;
  exported_at: string;
  app: string;
  content: ProtocolContent;
  checksum: { algorithm: "sha256"; value: string; note: string };
}

const CHECKSUM_NOTE = "Контрольная сумма обнаруживает повреждение содержимого; это не подпись и не доказательство подлинности.";

function pick<T extends object>(source: T, fields: readonly string[]): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const key of fields) {
    if (key in source) out[key] = (source as Record<string, unknown>)[key];
  }
  return out as Partial<T>;
}

const META_FIELDS = [
  "schema", "created_at", "conditions_requested", "conditions_applied", "input_fingerprint", "input_parts", "code",
  "model", "provider", "horizon_hours", "severity_profile", "unknown_note"
] as const;

const FRAME_FIELDS: Record<string, readonly string[]> = {
  phase: ["kind", "atMs", "phase"],
  tick: ["kind", "atMs", "elapsedMs"],
  agent: ["kind", "atMs", "event"],
  core: ["kind", "atMs", "core"],
  stage: ["kind", "atMs", "stage", "elapsedMs", "state", "facts"],
  screen: ["kind", "atMs", "elapsedMs"]
};

function exportableFrame(frame: RecordedFrame): RecordedFrame {
  return pick(frame, FRAME_FIELDS[frame.kind] ?? ["kind", "atMs"]) as RecordedFrame;
}

/** Только явный список полей приложения: без окружения, заголовков и посторонних ключей. */
export function exportableRecord(record: RunRecord): RunRecord {
  return {
    schema: record.schema, run_id: record.run_id, recorded_at: record.recorded_at, label: record.label,
    origin: record.origin, form: pick(record.form, FORM_FIELDS), query: record.query,
    meta: record.meta ? (pick(record.meta, META_FIELDS) as RunRecord["meta"]) : null,
    payload: pick(record.payload, PAYLOAD_FIELDS) as ScreenPayload, events: record.events.map(exportableFrame),
    duration_ms: record.duration_ms
  };
}

export function buildProtocol(a: RunRecord | null, b: RunRecord | null, now: Date = new Date(),
  research: ResearchSummary | null = null): Protocol {
  const content: ProtocolContent = {
    a: a ? exportableRecord(a) : null,
    b: b ? exportableRecord(b) : null,
    differences: a && b ? comparePair(a, b) : null,
    research
  };
  const clean = JSON.parse(JSON.stringify(content)) as ProtocolContent;
  return {
    format: PROTOCOL_FORMAT, version: PROTOCOL_VERSION, exported_at: now.toISOString(), app: "neftecode-frontend",
    content: clean,
    checksum: { algorithm: "sha256", value: sha256Hex(canonicalJson(clean)), note: CHECKSUM_NOTE }
  };
}

export function serializeProtocol(protocol: Protocol): string {
  return JSON.stringify(protocol, null, 2);
}

function object(value: unknown, where: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProtocolError(`${where}: ожидался объект`);
  }
  return value as Record<string, unknown>;
}

function assertFinite(value: unknown, path: string, depth = 0): void {
  if (depth > 60) throw new ProtocolError(`${path}: слишком глубокая вложенность`);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new ProtocolError(`${path}: число не конечно`);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertFinite(item, `${path}[${index}]`, depth + 1));
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) assertFinite(item, `${path}.${key}`, depth + 1);
  }
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

const FRAME_KINDS = ["phase", "tick", "agent", "core", "stage", "screen"];
const STAGE_STATES = ["pending", "running", "done", "skipped", "failed"];

function validateFrame(raw: unknown, where: string): void {
  const item = object(raw, where);
  if (typeof item.kind !== "string" || !FRAME_KINDS.includes(item.kind)) {
    throw new ProtocolError(`${where}: неизвестный вид события`);
  }
  if (!isFiniteNumber(item.atMs) || item.atMs < 0) throw new ProtocolError(`${where}: время события неверно`);
  if (item.kind === "phase") {
    const phase = object(item.phase, `${where}.phase`);
    for (const key of ["key", "label", "detail"]) {
      if (typeof phase[key] !== "string") throw new ProtocolError(`${where}: у фазы нет поля ${key}`);
    }
    if (!isFiniteNumber(phase.elapsed_ms)) throw new ProtocolError(`${where}: у фазы нет времени`);
    if (phase.state !== undefined && (typeof phase.state !== "string" || !STAGE_STATES.includes(phase.state))) {
      throw new ProtocolError(`${where}: недопустимое состояние фазы`);
    }
  } else if (item.kind === "tick") {
    if (!isFiniteNumber(item.elapsedMs)) throw new ProtocolError(`${where}: у отсчёта нет времени`);
  } else if (item.kind === "core") {
    const core = object(item.core, `${where}.core`);
    if (core.phase !== "preliminary" || typeof core.note !== "string" || !isFiniteNumber(core.core_s)) {
      throw new ProtocolError(`${where}: предварительный результат ядра неполный`);
    }
  } else if (item.kind === "agent") {
    const event = object(item.event, `${where}.event`);
    if (typeof event.agent !== "string" || typeof event.kind !== "string" ||
        !isFiniteNumber(event.seq) || !isFiniteNumber(event.step)) {
      throw new ProtocolError(`${where}: событие агента неполное`);
    }
  } else if (item.kind === "stage") {
    if (typeof item.stage !== "string" || !isFiniteNumber(item.elapsedMs)) {
      throw new ProtocolError(`${where}: у этапа нет идентификатора или времени`);
    }
    if (item.state !== undefined && item.state !== null &&
        (typeof item.state !== "string" || !STAGE_STATES.includes(item.state))) {
      throw new ProtocolError(`${where}: недопустимое состояние этапа`);
    }
    if (item.facts !== undefined && item.facts !== null) object(item.facts, `${where}.facts`);
  } else if (!isFiniteNumber(item.elapsedMs)) {
    throw new ProtocolError(`${where}: у итогового кадра нет времени`);
  }
}

function checkShape(check: Check, value: unknown, where: string): void {
  try {
    check(value, where);
  } catch (error) {
    if (error instanceof ShapeError) throw new ProtocolError(`${where}: структура не соответствует записи прогона (${error.message})`);
    throw error;
  }
}

function validateRecord(raw: unknown, where: string): RunRecord {
  const record = object(raw, where);
  if (record.schema !== RECORD_SCHEMA) throw new ProtocolError(`${where}: неподдерживаемая схема записи «${String(record.schema)}»`);
  for (const key of ["run_id", "recorded_at", "label"]) {
    if (typeof record[key] !== "string") throw new ProtocolError(`${where}: поле ${key} отсутствует`);
  }
  if (record.form === undefined || record.form === null) throw new ProtocolError(`${where}: нет условий прогона (form)`);
  checkShape(formShape, record.form, `${where}.form`);
  const payload = object(record.payload, `${where}.payload`);
  const decision = object(payload.decision, `${where}.payload.decision`);
  if (typeof decision.status !== "string") throw new ProtocolError(`${where}: у решения нет статуса`);
  checkShape(payloadShape, payload, `${where}.payload`);
  if (!Array.isArray(record.events)) throw new ProtocolError(`${where}: список событий отсутствует`);
  for (const [index, frame] of record.events.entries()) validateFrame(frame, `${where}.events[${index}]`);
  if (record.duration_ms !== null && !isFiniteNumber(record.duration_ms)) {
    throw new ProtocolError(`${where}: длительность записи не число`);
  }
  if (record.query !== null && typeof record.query !== "string") {
    throw new ProtocolError(`${where}: запрос записи не строка`);
  }
  if (record.meta === undefined) throw new ProtocolError(`${where}: нет поля meta (для неизвестных сведений ожидается null)`);
  checkShape(nullable(runMetaShape), record.meta, `${where}.meta`);
  return { ...(record as unknown as RunRecord), origin: "record" };
}

/** A/B: null — честное отсутствие записи; false, 0, "" и прочее — повреждённый пакет. */
function recordSlot(raw: unknown, where: string): RunRecord | null {
  if (raw === null) return null;
  if (raw === undefined) throw new ProtocolError(`${where}: поле отсутствует (для пустого слота ожидается null)`);
  return validateRecord(raw, where);
}

/**
 * Пробное восстановление и сравнение до изменения экрана: пакет открывается целиком или не
 * открывается вовсе. Ошибка здесь означает дыру в структурной проверке — показываем её как
 * ошибку файла, а не как падение интерфейса.
 */
function rehearse(a: RunRecord | null, b: RunRecord | null): void {
  try {
    for (const item of [a, b]) if (item) hydrateRun(item, recordInfoOf(item, null));
    if (a && b) comparePair(a, b);
  } catch (error) {
    if (error instanceof ProtocolError) throw error;
    throw new ProtocolError("Запись не удалось восстановить: структура файла не соответствует протоколу. Текущий экран сохранён.");
  }
}

export interface ParsedProtocol {
  protocol: Protocol;
  a: RunRecord | null;
  b: RunRecord | null;
  research: ResearchSummary | null;
}

/** Разбор и проверка пакета. Содержимое не исполняется и не дополняется вымышленными полями. */
export function parseProtocol(text: string): ParsedProtocol {
  if (text.length > MAX_PROTOCOL_BYTES) throw new ProtocolError("Файл слишком большой для протокола решения");
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ProtocolError("Файл не является корректным JSON: пакет повреждён или это другой файл");
  }
  const root = object(raw, "пакет");
  if (root.format !== PROTOCOL_FORMAT) throw new ProtocolError("Это не протокол решения Нефтекода (неизвестный формат файла)");
  if (root.version !== PROTOCOL_VERSION) {
    throw new ProtocolError(`Версия пакета ${String(root.version)} не поддерживается (нужна ${PROTOCOL_VERSION})`);
  }
  const content = object(root.content, "содержимое");
  const checksum = object(root.checksum, "контрольная сумма");
  assertFinite(content, "содержимое");
  if (checksum.algorithm !== "sha256" || typeof checksum.value !== "string") {
    throw new ProtocolError("Контрольная сумма отсутствует или в неизвестном формате");
  }
  if (sha256Hex(canonicalJson(content)) !== checksum.value) {
    throw new ProtocolError("Контрольная сумма не совпала: содержимое изменено или повреждено");
  }
  const a = recordSlot(content.a, "запись A");
  const b = recordSlot(content.b, "запись B");
  if (!a && !b) throw new ProtocolError("В пакете нет ни одной записи прогона");
  let research: ResearchSummary | null;
  try {
    research = researchSlot(content.research);
  } catch (error) {
    if (error instanceof ResearchSummaryError) throw new ProtocolError(`Сводка исследования: ${error.message}`);
    throw error;
  }
  rehearse(a, b);
  return { protocol: root as unknown as Protocol, a, b, research };
}

export function protocolFileName(record: RunRecord | null, now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const scenario = String((record?.form as Record<string, unknown> | undefined)?.scenario ?? "run");
  return `neftecode-protocol-${scenario}-${stamp}.json`;
}

export function eventTimes(record: RunRecord): number[] {
  return record.events.map((frame: RecordedFrame) => frame.atMs);
}
