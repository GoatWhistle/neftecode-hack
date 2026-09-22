import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { streamDecision } from "./stream";
import type { StreamHandlers } from "./stream";

const here = dirname(fileURLToPath(import.meta.url));
// Реальная запись /api/stream своего backend (LLM_PROVIDER=scripted), см. fixtures/README.md —
// не переписанный вручную список событий, а фактический прогон scenario=baseline, snapshot=20260105-080000.
const RECORDED_SSE = readFileSync(
  join(here, "..", "fixtures", "stream-baseline-2026-01-05.sse"),
  "utf-8"
);

function bodyFrom(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    }
  });
}

function handlers(): StreamHandlers & { calls: Record<string, unknown[]> } {
  const calls: Record<string, unknown[]> = {
    phase: [], tick: [], agent: [], stage: [], screen: [], failed: [], end: []
  };
  return {
    calls,
    onPhase: (p) => calls.phase!.push(p),
    onTick: (ms) => calls.tick!.push(ms),
    onAgent: (e) => calls.agent!.push(e),
    onStage: (stage, ms, state, facts) => calls.stage!.push({ stage, ms, state, facts }),
    onScreen: (payload, ms) => calls.screen!.push({ payload, ms }),
    onFailed: (msg) => calls.failed!.push(msg),
    onEnd: () => calls.end!.push(true)
  };
}

describe("streamDecision — реальная запись /api/stream (F6)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(bodyFrom(RECORDED_SSE), { status: 200 })
    ));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("разбирает phase/stage/agent/screen/end из настоящего прогона", async () => {
    const h = handlers();
    await streamDecision("?scenario=baseline", h, new AbortController().signal);

    expect(h.calls.phase!.length).toBeGreaterThan(0);
    expect(h.calls.stage!.length).toBeGreaterThan(0);
    expect(h.calls.agent!.length).toBeGreaterThan(0);
    expect(h.calls.screen!.length).toBe(1);
    expect(h.calls.end!.length).toBe(1);
    expect(h.calls.failed!.length).toBe(0);

    const screen = h.calls.screen![0] as { payload: { state: string; decision: { status: string } } };
    expect(screen.payload.state).toBe("decision");
    expect(screen.payload.decision.status).toBe("hold");
  });

  it("сообщает об HTTP-ошибке до старта этапов, а не молчит", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 404 })));
    const h = handlers();
    await expect(
      streamDecision("?scenario=baseline", h, new AbortController().signal)
    ).rejects.toThrow(/404/);
  });

  it("обрыв потока до screen оставляет решение непереданным, а не додумывает его", async () => {
    // Негативный тестовый поток (не запись backend): обрезаем реальную запись до первого
    // «screen», чтобы проверить путь «соединение прервалось раньше решения».
    const cut = RECORDED_SSE.slice(0, RECORDED_SSE.indexOf("event: screen"));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(bodyFrom(cut), { status: 200 })));
    const h = handlers();
    await streamDecision("?scenario=baseline", h, new AbortController().signal);
    expect(h.calls.screen!.length).toBe(0);
    expect(h.calls.stage!.length).toBeGreaterThan(0);
    expect(h.calls.failed!.length).toBe(1);
  });
});

describe("P5: предварительный результат ядра", () => {
  it("кадр core уходит в onCore, запись с ним проходит протокол", async () => {
    const { parseProtocol, buildProtocol, serializeProtocol } = await import("./protocol");
    const { fixture } = await import("./testRecords");
    const { buildRecord } = await import("./record");
    const payload = fixture("normal");
    const record = buildRecord({ payload, form: null, query: "?scenario=baseline", label: "x",
      tape: { frames: [{ kind: "core", atMs: 1, core: { phase: "preliminary", decision_id: "d", status: "hold",
        plan_id: "hold", core_s: 0.2, note: "предварительно", elapsedMs: 5 } },
      { kind: "screen", atMs: 2, payload, elapsedMs: 9 }] }, durationMs: 9 });
    const parsed = parseProtocol(serializeProtocol(buildProtocol(record, null)));
    expect(parsed.a!.events.some((f) => f.kind === "core")).toBe(true);
  });
});

describe("terminal is final", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([false, true])("ignores late events, separate chunks=%s", async (separate) => {
    const terminal = RECORDED_SSE.slice(RECORDED_SSE.indexOf("event: screen"));
    const late = 'event: failed\ndata: {"message":"late"}\n\nevent: core\ndata: {}\n\n';
    let sent = false;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (!sent) {
          sent = true;
          controller.enqueue(new TextEncoder().encode(terminal + (separate ? "" : late)));
        } else {
          controller.enqueue(new TextEncoder().encode(late));
          controller.close();
        }
      }
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body)));
    const h = handlers();
    h.onCore = vi.fn();
    await streamDecision("", h, new AbortController().signal);
    expect(h.calls.screen).toHaveLength(1);
    expect(h.calls.failed).toHaveLength(0);
    expect(h.onCore).not.toHaveBeenCalled();
    expect(h.calls.end).toHaveLength(1);
  });

  it("does not read transport errors after terminal", async () => {
    const reader = { read: vi.fn()
      .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(RECORDED_SSE) })
      .mockRejectedValueOnce(new Error("late disconnect")), cancel: vi.fn(async () => {}) };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, body: { getReader: () => reader } })));
    const h = handlers();
    await streamDecision("", h, new AbortController().signal);
    expect(reader.read).toHaveBeenCalledTimes(1);
    expect(h.calls.screen).toHaveLength(1);
    expect(h.calls.failed).toHaveLength(0);
  });

  it("replay ignores frames after screen", async () => {
    const { playTape } = await import("./replay");
    const { fixture } = await import("./testRecords");
    const h = handlers();
    await playTape({ frames: [
      { kind: "screen", atMs: 0, elapsedMs: 1, payload: fixture("normal") },
      { kind: "tick", atMs: 0, elapsedMs: 99 }
    ] }, h, new AbortController().signal);
    expect(h.calls.screen).toHaveLength(1);
    expect(h.calls.tick).toHaveLength(0);
  });
});
