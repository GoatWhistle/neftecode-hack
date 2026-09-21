import type { ScreenPayload } from "../types";
import type { RecordedFrame, RunRecord } from "./record";
import { RECORD_SCHEMA } from "./record";
import { sha256Hex } from "./sha256";
import { comparePair } from "./pair";

export const PROTOCOL_FORMAT = "neftecode.decision-protocol";
export const PROTOCOL_VERSION = 1;
export const MAX_PROTOCOL_BYTES = 8 * 1024 * 1024;

const PAYLOAD_FIELDS = [
  "state", "title", "status_label", "decision", "explanation", "inventories", "sources", "rule_origin",
  "state_origin", "decision_time", "forecast", "forecast_used", "defaults", "applied", "injection", "snapshot",
  "binding", "run_meta", "decision_timeout_s", "agentic_state"
] as const;

const FORM_FIELDS = [
  "scenario", "snapshot", "fault", "crude_sulfur_wt_pct", "product_sulfur_mgkg", "product_t95_c",
  "product_cetane_number", "throughput_tph", "tank", "tank_inventory", "tank_available"
] as const;

export class ProtocolError extends Error {}

export interface ProtocolContent {
  a: RunRecord | null;
  b: RunRecord | null;
  differences: unknown;
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

export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
}

function pick<T extends object>(source: T, fields: readonly string[]): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const key of fields) {
    if (key in source) out[key] = (source as Record<string, unknown>)[key];
  }
  return out as Partial<T>;
}

/** Только явный список полей приложения: без окружения, заголовков и посторонних ключей. */
export function exportableRecord(record: RunRecord): RunRecord {
  return {
    schema: record.schema, run_id: record.run_id, recorded_at: record.recorded_at, label: record.label,
    origin: record.origin, form: pick(record.form, FORM_FIELDS), query: record.query, meta: record.meta,
    payload: pick(record.payload, PAYLOAD_FIELDS) as ScreenPayload, events: record.events,
    duration_ms: record.duration_ms
  };
}

export function buildProtocol(a: RunRecord | null, b: RunRecord | null, now: Date = new Date()): Protocol {
  const content: ProtocolContent = {
    a: a ? exportableRecord(a) : null,
    b: b ? exportableRecord(b) : null,
    differences: a && b ? comparePair(a, b) : null
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

function validateRecord(raw: unknown, where: string): RunRecord {
  const record = object(raw, where);
  if (record.schema !== RECORD_SCHEMA) throw new ProtocolError(`${where}: неподдерживаемая схема записи «${String(record.schema)}»`);
  for (const key of ["run_id", "recorded_at", "label"]) {
    if (typeof record[key] !== "string") throw new ProtocolError(`${where}: поле ${key} отсутствует`);
  }
  const payload = object(record.payload, `${where}.payload`);
  const decision = object(payload.decision, `${where}.payload.decision`);
  if (typeof decision.status !== "string") throw new ProtocolError(`${where}: у решения нет статуса`);
  object(payload.explanation, `${where}.payload.explanation`);
  if (!Array.isArray(record.events)) throw new ProtocolError(`${where}: список событий отсутствует`);
  for (const [index, frame] of record.events.entries()) {
    const item = object(frame, `${where}.events[${index}]`);
    if (typeof item.kind !== "string" || typeof item.atMs !== "number") {
      throw new ProtocolError(`${where}: событие ${index} без вида или времени`);
    }
  }
  return { ...(record as unknown as RunRecord), origin: "record" };
}

export interface ParsedProtocol {
  protocol: Protocol;
  a: RunRecord | null;
  b: RunRecord | null;
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
  const a = content.a ? validateRecord(content.a, "запись A") : null;
  const b = content.b ? validateRecord(content.b, "запись B") : null;
  if (!a && !b) throw new ProtocolError("В пакете нет ни одной записи прогона");
  return { protocol: root as unknown as Protocol, a, b };
}

export function protocolFileName(record: RunRecord | null, now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const scenario = String((record?.form as Record<string, unknown> | undefined)?.scenario ?? "run");
  return `neftecode-protocol-${scenario}-${stamp}.json`;
}

export function eventTimes(record: RunRecord): number[] {
  return record.events.map((frame: RecordedFrame) => frame.atMs);
}
