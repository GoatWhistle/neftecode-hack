import type { ScreenPayload } from "../types";
import { isError, isScreen } from "../types";
import type { AgentEvent, PhaseEvent } from "./types";

export interface StreamHandlers {
  onPhase: (phase: PhaseEvent) => void;
  onTick: (elapsedMs: number) => void;
  onAgent: (event: AgentEvent) => void;
  onStage: (stage: string, elapsedMs: number, state?: string) => void;
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

function dispatch(event: string, data: Record<string, unknown>, handlers: StreamHandlers): void {
  if (event === "phase") {
    handlers.onPhase(data as unknown as PhaseEvent);
    return;
  }
  if (event === "tick") {
    handlers.onTick(Number(data["elapsed_ms"] ?? 0));
    return;
  }
  if (event === "agent") {
    const raw = data["event"] as Record<string, unknown> | undefined;
    if (raw) handlers.onAgent({ ...raw, elapsedMs: Number(data["elapsed_ms"] ?? 0) } as unknown as AgentEvent);
    return;
  }
  if (event === "stage") {
    handlers.onStage(String(data["stage"] ?? ""), Number(data["elapsed_ms"] ?? 0),
      data["state"] === undefined ? undefined : String(data["state"]));
    return;
  }
  if (event === "failed") {
    handlers.onFailed(String(data["message"] ?? "сервер прервал расчёт"));
    return;
  }
  if (event === "screen") {
    const payload = data["payload"] as ScreenPayload | null;
    if (payload && isError(payload)) {
      handlers.onFailed(String((payload as { message?: unknown }).message ?? "сервер вернул ошибку"));
      return;
    }
    if (payload && isScreen(payload)) {
      handlers.onScreen(payload, Number(data["elapsed_ms"] ?? 0));
      return;
    }
    handlers.onFailed("сервер вернул payload неизвестной формы");
    return;
  }
  if (event === "end") handlers.onEnd();
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
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut !== -1) {
      const frame = parseFrame(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (frame) dispatch(frame.event, frame.data as Record<string, unknown>, handlers);
      cut = buffer.indexOf("\n\n");
    }
  }
}
