import { describe, expect, it } from "vitest";
import { buildProtocol, canonicalJson, parseProtocol, ProtocolError, serializeProtocol } from "./protocol";
import { hydrateRun, recordInfoOf } from "./hydrate";
import { comparePair } from "./pair";
import { tapeOf } from "./record";
import { sha256Hex } from "./sha256";
import { record } from "./testRecords";

const roundTrip = (a: ReturnType<typeof record> | null, b: ReturnType<typeof record> | null) =>
  parseProtocol(serializeProtocol(buildProtocol(a, b, new Date("2026-09-22T10:00:00Z"))));

describe("sha256", () => {
  it("совпадает с эталонными значениями", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("а".repeat(200))).toHaveLength(64);
  });
});

describe("протокол решения", () => {
  it("экспорт → импорт сохраняет итог, условия, карту планов, события и их порядок", () => {
    const a = record("risk");
    const back = roundTrip(a, null).a!;
    expect(back.origin).toBe("record");
    expect(back.payload.decision.status).toBe(a.payload.decision.status);
    expect(back.payload.decision.tradeoff).toEqual(a.payload.decision.tradeoff);
    expect(back.payload.decision.severity).toEqual(a.payload.decision.severity);
    expect(back.payload.explanation.warnings).toEqual(a.payload.explanation.warnings);
    expect(back.meta?.conditions_requested).toEqual(a.meta?.conditions_requested);
    expect(back.meta?.input_fingerprint).toBe(a.meta?.input_fingerprint);
    expect(back.events.map((f) => [f.kind, f.atMs])).toEqual(a.events.map((f) => [f.kind, f.atMs]));
    expect(back.events.find((f) => f.kind === "screen")).not.toHaveProperty("payload");
    const tape = tapeOf(back)!;
    expect(tape.frames.at(-1)).toMatchObject({ kind: "screen", payload: back.payload });
  });

  it("сохраняет отказ и отсутствие стоимости как неизвестное, а не ноль", () => {
    const refused = record("risk-reserve-off");
    const back = roundTrip(refused, null).a!;
    expect(back.payload.decision.status).toBe("refuse");
    expect(back.payload.decision.cost_per_tonne).toBeNull();
    expect(back.payload.decision.production_t).toBeNull();
    expect(back.payload.explanation.next_steps).toEqual(refused.payload.explanation.next_steps);
    const bad = roundTrip(record("bad-data"), null).a!;
    expect(bad.payload.decision.gate).toBe(record("bad-data").payload.decision.gate);
  });

  it("пара A/B восстанавливает то же сравнение", () => {
    const a = record("risk");
    const b = record("risk-frozen-pak", { fault: "frozen_pak" });
    const back = roundTrip(a, b);
    expect(comparePair(back.a!, back.b!)).toEqual(comparePair(a, b));
    expect(back.protocol.content.differences).toEqual(JSON.parse(JSON.stringify(comparePair(a, b))));
  });

  it("не пропускает лишние поля приложения и не тянет окружение", () => {
    const a = structuredClone(record("risk"));
    (a.payload as unknown as Record<string, unknown>).secret_env = "TOKEN=abc";
    const text = serializeProtocol(buildProtocol(a, null));
    expect(text).not.toContain("TOKEN=abc");
    expect(text).not.toContain("secret_env");
  });

  it("повреждённые и неподдерживаемые пакеты дают понятную ошибку", () => {
    const good = serializeProtocol(buildProtocol(record("risk"), null));
    expect(() => parseProtocol("не json")).toThrow(ProtocolError);
    expect(() => parseProtocol(JSON.stringify({ a: 1 }))).toThrow(/не протокол решения/);
    expect(() => parseProtocol(good.replace('"version": 1', '"version": 9'))).toThrow(/не поддерживается/);
    expect(() => parseProtocol(good.replace("recommend_scenario", "recommend_scenarix"))).toThrow(/Контрольная сумма не совпала/);
    const broken = JSON.parse(good);
    broken.checksum = undefined;
    expect(() => parseProtocol(JSON.stringify(broken))).toThrow(ProtocolError);
    expect(() => parseProtocol("x".repeat(9 * 1024 * 1024))).toThrow(/слишком большой/);
  });

  it("отвергает нечисловые значения и записи без обязательных полей", () => {
    const protocol = buildProtocol(record("risk"), null);
    const forged = JSON.parse(JSON.stringify(protocol));
    forged.content.a.payload.decision.status = 5;
    forged.checksum.value = sha256Hex(canonicalJson(forged.content));
    expect(() => parseProtocol(JSON.stringify(forged))).toThrow(/статуса/);
    const empty = buildProtocol(null, null);
    expect(() => parseProtocol(serializeProtocol(empty))).toThrow(/нет ни одной записи/);
    const inf = JSON.parse(JSON.stringify(protocol));
    inf.content.a.duration_ms = 1e999;
    expect(() => parseProtocol(JSON.stringify(inf).replace('"duration_ms":null', '"duration_ms":1e999'))).toThrow(ProtocolError);
  });

  it("запись открывается без сети и помечена как запись с исходной датой и provider", () => {
    const a = record("risk");
    const back = roundTrip(a, null).a!;
    const state = hydrateRun(back, recordInfoOf(back, "2026-09-22T10:00:00.000Z"));
    expect(state.status).toBe("done");
    expect(state.record).toMatchObject({ recordedAt: a.recorded_at, provider: "scripted" });
    expect(state.payload?.decision.decision_id).toBe(a.payload.decision.decision_id);
    expect(state.stages.decision).toBe("done");
    expect(state.live).toBe(false);
  });
});

describe("структурная проверка импорта при верной контрольной сумме", () => {
  const forged = (mutate: (frames: Record<string, unknown>[]) => void) => {
    const protocol = JSON.parse(serializeProtocol(buildProtocol(record("risk"), null))) as {
      content: { a: { events: Record<string, unknown>[] } }; checksum: { value: string };
    };
    mutate(protocol.content.a.events);
    protocol.checksum.value = sha256Hex(canonicalJson(protocol.content));
    return JSON.stringify(protocol);
  };

  it("фаза с phase=null отклоняется до восстановления", () => {
    const text = forged((frames) => { frames[0] = { kind: "phase", atMs: 0, phase: null }; });
    expect(() => parseProtocol(text)).toThrow(ProtocolError);
  });

  it("неизвестный вид события, отрицательное время и этап без идентификатора отклоняются", () => {
    expect(() => parseProtocol(forged((f) => { f[0] = { kind: "boom", atMs: 0 }; }))).toThrow(ProtocolError);
    expect(() => parseProtocol(forged((f) => { f[0] = { ...f[0], atMs: -1 }; }))).toThrow(ProtocolError);
    expect(() => parseProtocol(forged((f) => { f[1] = { kind: "stage", atMs: 1, elapsedMs: 1 }; }))).toThrow(ProtocolError);
  });

  it("недопустимое состояние этапа и событие агента без полей отклоняются", () => {
    expect(() => parseProtocol(forged((f) => { f[1] = { ...f[1], state: "weird" }; }))).toThrow(ProtocolError);
    expect(() => parseProtocol(forged((f) => { f.push({ kind: "agent", atMs: 9000, event: {} }); }))).toThrow(ProtocolError);
  });

  it("корректный протокол по-прежнему восстанавливается", () => {
    const parsed = parseProtocol(forged(() => {}));
    expect(() => hydrateRun(parsed.a!, recordInfoOf(parsed.a!, null))).not.toThrow();
  });
});

