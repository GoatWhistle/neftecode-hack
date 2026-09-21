import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildProtocol, parseProtocol, serializeProtocol } from "./protocol";
import { record } from "./testRecords";
import { useRun } from "./useRun";

describe("открытие записи", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("результат доступен сразу, повтор событий идёт без обращений к расчётному API", async () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error("сеть не должна вызываться")));
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("EventSource", vi.fn(() => { throw new Error("SSE не должен открываться"); }));
    window.matchMedia = window.matchMedia ?? ((q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }) as never);
    const parsed = parseProtocol(serializeProtocol(buildProtocol(record("risk"), null)));
    const { result } = renderHook(() => useRun());
    act(() => result.current.openRecord(parsed.a!, parsed.protocol.exported_at));
    expect(result.current.run.status).toBe("done");
    expect(result.current.run.record?.provider).toBe("scripted");
    expect(result.current.run.payload?.decision.status).toBe(parsed.a!.payload.decision.status);
    expect(result.current.canReplay).toBe(true);
    await act(async () => {
      result.current.replay();
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(result.current.run.record).not.toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
