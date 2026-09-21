import type { RunMeta, ScreenPayload } from "../types";
import type { RunTape } from "./replay";
import type { Conditions } from "./options";

export const RECORD_SCHEMA = "neftecode.run-record/1";

export interface RecordedFrame {
  kind: "phase" | "tick" | "agent" | "stage" | "screen";
  atMs: number;
  [key: string]: unknown;
}

export interface RunRecord {
  schema: typeof RECORD_SCHEMA;
  run_id: string;
  recorded_at: string;
  label: string;
  origin: "live" | "record";
  form: Partial<Conditions>;
  query: string | null;
  meta: RunMeta | null;
  payload: ScreenPayload;
  events: RecordedFrame[];
  duration_ms: number | null;
}

let counter = 0;

export function newRunId(now: number = Date.now()): string {
  counter += 1;
  return `run-${now.toString(36)}-${counter.toString(36)}`;
}

/** Кадры ленты без повторного payload: payload хранится в записи один раз. */
export function framesOf(tape: RunTape | null): RecordedFrame[] {
  if (!tape) return [];
  return tape.frames.map((frame) => {
    if (frame.kind !== "screen") return { ...frame } as unknown as RecordedFrame;
    const { payload: _payload, ...rest } = frame;
    return rest as unknown as RecordedFrame;
  });
}

export function tapeOf(record: RunRecord): RunTape | null {
  if (record.events.length === 0) return null;
  return {
    frames: record.events.map((frame) =>
      frame.kind === "screen" ? ({ ...frame, payload: record.payload } as never) : (frame as never)
    )
  };
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const inner of Object.values(value as Record<string, unknown>)) deepFreeze(inner);
  }
  return value;
}

export interface BuildInput {
  payload: ScreenPayload;
  form: Conditions | null;
  query: string | null;
  label: string;
  tape: RunTape | null;
  durationMs: number | null;
  now?: Date;
}

/** Неизменяемая запись завершённого прогона: копия, не ссылка на редактируемое состояние. */
export function buildRecord(input: BuildInput): RunRecord {
  const copy = structuredClone({
    payload: input.payload,
    form: input.form ?? {},
    events: framesOf(input.tape)
  });
  return deepFreeze({
    schema: RECORD_SCHEMA,
    run_id: newRunId(),
    recorded_at: (input.now ?? new Date()).toISOString(),
    label: input.label,
    origin: "live" as const,
    form: copy.form,
    query: input.query,
    meta: copy.payload.run_meta ?? null,
    payload: copy.payload,
    events: copy.events,
    duration_ms: input.durationMs
  });
}
