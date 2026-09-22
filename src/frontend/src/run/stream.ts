import type { ScreenPayload } from "../types";
import { isError, isScreen } from "../types";
import type { AgentEvent, CoreEvent, PhaseEvent, StageFacts } from "./types";

export interface StreamHandlers {
  onPhase: (phase: PhaseEvent) => void;
  onTick: (elapsedMs: number) => void;
  onAgent: (event: AgentEvent) => void;
  onCore?: (event: CoreEvent) => void;
  onStage: (stage: string, elapsedMs: number, state: string | undefined, facts: StageFacts) => void;
  onScreen: (payload: ScreenPayload, elapsedMs: number) => void;
  onFailed: (message: string) => void;
  onEnd: () => void;
}

function parseFrame(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const lines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) lines.push(line.slice(5).trim());
  }
  if (lines.length === 0) return null;
  try {
    return { event, data: JSON.parse(lines.join("\n")) as unknown };
  } catch {
    return null;
  }
}

function dispatch(event: string, data: Record<string, unknown>, handlers: StreamHandlers): boolean {
  if (event === "phase") {
    handlers.onPhase(data as unknown as PhaseEvent);
    return false;
  }
  if (event === "tick") {
    handlers.onTick(Number(data["elapsed_ms"] ?? 0));
    return false;
  }
  if (event === "agent") {
    const raw = data["event"] as Record<string, unknown> | undefined;
    if (raw) handlers.onAgent({ ...raw, elapsedMs: Number(data["elapsed_ms"] ?? 0) } as unknown as AgentEvent);
    return false;
  }
  if (event === "core") {
    handlers.onCore?.({ ...data, elapsedMs: Number(data["elapsed_ms"] ?? 0) } as unknown as CoreEvent);
    return false;
  }
  if (event === "stage") {
    const facts: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      if (key !== "stage" && key !== "state" && key !== "elapsed_ms") facts[key] = value;
    }
    handlers.onStage(String(data["stage"] ?? ""), Number(data["elapsed_ms"] ?? 0),
      data["state"] === undefined ? undefined : String(data["state"]), facts as StageFacts);
    return false;
  }
  if (event === "failed") {
    handlers.onFailed(String(data["message"] ?? "сервер прервал расчёт"));
    return true;
  }
  if (event === "screen") {
    const payload = data["payload"] as ScreenPayload | null;
    if (payload && isError(payload)) {
      handlers.onFailed(String((payload as { message?: unknown }).message ?? "сервер вернул ошибку"));
      return true;
    }
    if (payload && isScreen(payload)) {
      handlers.onScreen(payload, Number(data["elapsed_ms"] ?? 0));
      return true;
    }
    handlers.onFailed("сервер вернул payload неизвестной формы");
    return true;
  }
  if (event === "end") handlers.onEnd();
  return false;
}

export async function streamDecision(
  query: string,
  handlers: StreamHandlers,
  signal: AbortSignal
): Promise<void> {
  const response = await fetch(`/api/stream${query}`, { signal });
  if (!response.ok || !response.body) throw new Error(`сервер ответил ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let settled = false;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let cut = buffer.indexOf("\n\n");
      while (cut !== -1) {
        const frame = parseFrame(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        if (!signal.aborted && frame && dispatch(frame.event, frame.data as Record<string, unknown>, handlers)) {
          settled = true;
          handlers.onEnd();
          return;
        }
        if (signal.aborted) return;
        cut = buffer.indexOf("\n\n");
      }
    }
    if (!settled && !signal.aborted) {
      handlers.onFailed("поток оборвался: решение от сервера не получено");
    }
  } catch (reason) {
    if (signal.aborted || settled) return;
    throw reason;
  } finally {
    reader.cancel().catch(() => undefined);
  }
}
