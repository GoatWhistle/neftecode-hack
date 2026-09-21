import { describe, expect, it } from "vitest";
import { stageRan } from "./sequence";
import type { ScreenPayload } from "../types";
import agentsOff from "../fixtures/decide-agents-off-2026-01-05.json";
import agentsOn from "../fixtures/decide-sour-crude-agents.json";

describe("O2 — agentic_state (F4), реальные фикстуры", () => {
  it("агенты выключены: stageRan('agents') = false, decision.agentic отсутствует", () => {
    const payload = agentsOff as unknown as ScreenPayload;
    expect(payload.agentic_state?.outcome).toBe("skipped");
    expect(payload.decision.agentic).toBeUndefined();
    expect(stageRan("agents", payload)).toBe(false);
  });

  it("агенты реально консультировались: agentic_state отсутствует, stageRan('agents') = true", () => {
    const payload = agentsOn as unknown as ScreenPayload;
    expect(payload.agentic_state).toBeUndefined();
    expect(payload.decision.agentic).toBeTruthy();
    expect(stageRan("agents", payload)).toBe(true);
  });
});
