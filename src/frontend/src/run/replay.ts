import type { ScreenPayload } from "../types";
import type { StreamHandlers } from "./stream";
import type { AgentEvent, PhaseEvent, StageFacts } from "./types";

export const REPLAY_PAUSE_CAP_MS = 2000;

interface PhaseFrame { kind: "phase"; atMs: number; phase: PhaseEvent }
interface TickFrame { kind: "tick"; atMs: number; elapsedMs: number }
interface AgentFrame { kind: "agent"; atMs: number; event: AgentEvent }
interface StageFrame {
  kind: "stage";
  atMs: number;
  stage: string;
  elapsedMs: number;
  state: string | undefined;
  facts: StageFacts;
}
interface ScreenFrame { kind: "screen"; atMs: number; payload: ScreenPayload; elapsedMs: number }

export type ReplayFrame = PhaseFrame | TickFrame | AgentFrame | StageFrame | ScreenFrame;

export interface RunTape {
  frames: ReplayFrame[];
}

export interface TapeRecorder {
  onPhase: (phase: PhaseEvent) => void;
  onTick: (elapsedMs: number) => void;
  onAgent: (event: AgentEvent) => void;
  onStage: (stage: string, elapsedMs: number, state: string | undefined, facts: StageFacts) => void;
  onScreen: (payload: ScreenPayload, elapsedMs: number) => void;
  snapshot: () => RunTape;
  reset: () => void;
}

export function createTapeRecorder(): TapeRecorder {
  let frames: ReplayFrame[] = [];
  let startedAt: number | null = null;

  const stamp = (): number => {
    if (startedAt === null) startedAt = performance.now();
    return performance.now() - startedAt;
  };

  return {
    onPhase: (phase) => frames.push({ kind: "phase", atMs: stamp(), phase }),
    onTick: (elapsedMs) => frames.push({ kind: "tick", atMs: stamp(), elapsedMs }),
    onAgent: (event) => frames.push({ kind: "agent", atMs: stamp(), event }),
    onStage: (stage, elapsedMs, state, facts) =>
      frames.push({ kind: "stage", atMs: stamp(), stage, elapsedMs, state, facts }),
    onScreen: (payload, elapsedMs) => frames.push({ kind: "screen", atMs: stamp(), payload, elapsedMs }),
    snapshot: () => ({ frames: [...frames] }),
    reset: () => {
      frames = [];
      startedAt = null;
    }
  };
}

function compressedDelay(gapMs: number): number {
  return Math.min(Math.max(0, gapMs), REPLAY_PAUSE_CAP_MS);
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    const abort = (): void => {
      window.clearTimeout(timer);
      resolve();
    };
    signal.addEventListener("abort", abort, { once: true });
  });
}

export async function playTape(
  tape: RunTape,
  handlers: Pick<StreamHandlers, "onPhase" | "onTick" | "onAgent" | "onStage" | "onScreen">,
  signal: AbortSignal
): Promise<void> {
  let previousAt = 0;
  for (const frame of tape.frames) {
    if (signal.aborted) return;
    const gap = frame.atMs - previousAt;
    previousAt = frame.atMs;
    await sleep(compressedDelay(gap), signal);
    if (signal.aborted) return;
    if (frame.kind === "phase") handlers.onPhase(frame.phase);
    else if (frame.kind === "tick") handlers.onTick(frame.elapsedMs);
    else if (frame.kind === "agent") handlers.onAgent(frame.event);
    else if (frame.kind === "stage") handlers.onStage(frame.stage, frame.elapsedMs, frame.state, frame.facts);
    else handlers.onScreen(frame.payload, frame.elapsedMs);
  }
}

export function canReplay(tape: RunTape | null): tape is RunTape {
  return tape !== null && tape.frames.length > 0;
}
