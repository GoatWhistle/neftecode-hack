import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScreenPayload } from "../types";
import { buildProtocol, parseProtocol, serializeProtocol } from "./protocol";
import { fixture, record } from "./testRecords";
import { useRun } from "./useRun";

/** Поток /api/stream с одним итоговым кадром: payload однозначно метит, какому прогону он принадлежит. */
function sse(payload: ScreenPayload): Response {
  const text = [
    `event: phase\ndata: ${JSON.stringify({ key: "accepted", label: "Запрос принят", detail: "", state: "done", elapsed_ms: 0 })}\n\n`,
    `event: stage\ndata: ${JSON.stringify({ stage: "trust", state: "done", usable: true, elapsed_ms: 5 })}\n\n`,
    `event: screen\ndata: ${JSON.stringify({ payload, elapsed_ms: 10 })}\n\n`,
    `event: end\ndata: ${JSON.stringify({ elapsed_ms: 11 })}\n\n`
  ].join("");
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    }
  });
  return new Response(body, { status: 200 });
}

/** Поток, который висит до отмены: для проверки Stop во время live. */
function hanging(signal: AbortSignal | undefined): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    }
  });
  return new Response(body, { status: 200 });
}

const first = fixture("normal");
const second = fixture("risk");

async function replayToEnd(result: { current: ReturnType<typeof useRun> }): Promise<void> {
  act(() => result.current.replay());
  await waitFor(() => expect(result.current.run.status).toBe("done"), { timeout: 8000 });
}

describe("повтор принадлежит конкретной завершённой записи", () => {
  beforeEach(() => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener() {},
      removeEventListener() {} })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("успех → успех → повтор: показан второй прогон с его запросом, без обращения к API", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(sse(first))
      .mockResolvedValueOnce(sse(second));
    vi.stubGlobal("fetch", fetchSpy);
    const { result } = renderHook(() => useRun());
    act(() => result.current.start("?run=first"));
    await waitFor(() => expect(result.current.run.status).toBe("done"));
    act(() => result.current.start("?run=second"));
    await waitFor(() => expect(result.current.run.payload?.decision.decision_id).toBe(second.decision.decision_id));
    expect(result.current.canReplay).toBe(true);
    await replayToEnd(result);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(result.current.run.query).toBe("?run=second");
    expect(result.current.run.payload?.decision.decision_id).toBe(second.decision.decision_id);
    expect(result.current.run.record).not.toBeNull();
    expect(result.current.run.live).toBe(false);
  });

  it("успех → ошибка сети: повтор недоступен и не склеивает старую ленту с новым запросом", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(sse(first))
      .mockRejectedValueOnce(new TypeError("network down")));
    const { result } = renderHook(() => useRun());
    act(() => result.current.start("?run=first"));
    await waitFor(() => expect(result.current.run.status).toBe("done"));
    act(() => result.current.start("?run=second"));
    await waitFor(() => expect(result.current.run.status).toBe("failed"));
    expect(result.current.canReplay).toBe(false);
    act(() => result.current.replay());
    expect(result.current.run.status).toBe("failed");
    expect(result.current.run.query).toBe("?run=second");
    expect(result.current.run.payload).toBeNull();
  });

  it("успех → Stop нового прогона: повтор недоступен до успешного завершения", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(sse(first))
      .mockImplementationOnce((_url: string, init?: RequestInit) => Promise.resolve(hanging(init?.signal ?? undefined))));
    const { result } = renderHook(() => useRun());
    act(() => result.current.start("?run=first"));
    await waitFor(() => expect(result.current.run.status).toBe("done"));
    act(() => result.current.start("?run=second"));
    expect(result.current.canReplay).toBe(false);
    act(() => result.current.stop());
    expect(result.current.run.status).toBe("stopped");
    expect(result.current.canReplay).toBe(false);
    act(() => result.current.replay());
    expect(result.current.run.status).toBe("stopped");
    expect(result.current.run.payload).toBeNull();
  });

  it("импорт → повтор → Stop: остаётся открытая запись со своим запросом и маркировкой", async () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error("сеть не должна вызываться")));
    vi.stubGlobal("fetch", fetchSpy);
    const saved = record("risk");
    const parsed = parseProtocol(serializeProtocol(buildProtocol(saved, null)));
    const { result } = renderHook(() => useRun());
    act(() => result.current.openRecord(parsed.a!, parsed.protocol.exported_at));
    act(() => result.current.replay());
    expect(result.current.run.status).toBe("running");
    expect(result.current.run.record?.runId).toBe(saved.run_id);
    act(() => result.current.stop());
    expect(result.current.run.status).toBe("stopped");
    expect(result.current.run.record?.runId).toBe(saved.run_id);
    expect(result.current.canReplay).toBe(true);
    await replayToEnd(result);
    expect(result.current.run.query).toBe(saved.query);
    expect(result.current.run.payload?.decision.decision_id).toBe(saved.payload.decision.decision_id);
    expect(result.current.run.record?.exportedAt).toBe(parsed.protocol.exported_at);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("смена сцены (reset) снимает повтор прежней записи", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(sse(first)));
    const { result } = renderHook(() => useRun());
    act(() => result.current.start("?run=first"));
    await waitFor(() => expect(result.current.canReplay).toBe(true));
    act(() => result.current.reset());
    expect(result.current.canReplay).toBe(false);
    act(() => result.current.replay());
    expect(result.current.run.status).toBe("idle");
  });

  it("повтор live-результата помечен как запись; adopt подставляет полную запись того же прогона", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(sse(first)));
    const { result } = renderHook(() => useRun());
    act(() => result.current.start("?run=first"));
    await waitFor(() => expect(result.current.run.status).toBe("done"));
    expect(result.current.run.record).toBeNull();
    const full = record("normal", { scenario: "baseline" }, "Норма");
    act(() => result.current.adopt(full));
    await replayToEnd(result);
    expect(result.current.run.record).toMatchObject({ runId: full.run_id, label: "Норма" });
  });
});
