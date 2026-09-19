import { useCallback, useEffect, useRef, useState } from "react";
import type { ScreenPayload } from "../types";
import { streamDecision } from "./stream";
import type { AgentEvent, RunPhase, RunState, StageState } from "./types";
import { EMPTY_RUN } from "./types";
import { advanceTo, LATE_STAGES, mergePhase, scrollTo, settled } from "./sequence";

const UNPACK_MS = 520;

export interface RunControls {
  run: RunState;
  start: (query: string) => void;
  stop: () => void;
  skip: () => void;
}

export function useRun(): RunControls {
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const abort = useRef<AbortController | null>(null);
  const timers = useRef<number[]>([]);

  const clearTimers = useCallback(() => {
    for (const id of timers.current) window.clearTimeout(id);
    timers.current = [];
  }, []);

  useEffect(() => {
    return () => {
      abort.current?.abort();
      for (const id of timers.current) window.clearTimeout(id);
    };
  }, []);

  const unpack = useCallback((payload: ScreenPayload) => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const step = reduced ? 0 : UNPACK_MS;
    setRun((prev) => ({ ...prev, payload, stages: { ...prev.stages, agents: "done" } }));
    LATE_STAGES.forEach((id, position) => {
      const at = window.setTimeout(() => {
        setRun((prev) => ({
          ...prev,
          stages: { ...prev.stages, [id]: "done" as StageState },
          status: position === LATE_STAGES.length - 1 ? "done" : prev.status
        }));
        scrollTo(id, reduced);
      }, step * (position + 1));
      timers.current.push(at);
    });
  }, []);

  const skip = useCallback(() => {
    clearTimers();
    setRun((prev) =>
      prev.payload === null ? prev : { ...prev, stages: settled(), status: "done" }
    );
  }, [clearTimers]);

  const start = useCallback(
    (query: string) => {
      abort.current?.abort();
      clearTimers();
      const controller = new AbortController();
      abort.current = controller;
      setRun({ ...EMPTY_RUN, status: "running" });
      const fail = (message: string): void =>
        setRun((prev) => ({
          ...prev,
          status: "failed",
          error: message,
          stages: { ...prev.stages, agents: "failed" as StageState }
        }));

      streamDecision(
        query,
        {
          onPhase: (event) =>
            setRun((prev) => {
              const phases: RunPhase[] = mergePhase(prev.phases, event);
              return { ...prev, phases, elapsedMs: event.elapsed_ms };
            }),
          onTick: (elapsedMs) => setRun((prev) => ({ ...prev, elapsedMs })),
          onStage: (stage, elapsedMs, state) => {
            const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            setRun((prev) => ({
              ...prev,
              elapsedMs,
              stages: advanceTo(prev.stages, stage, (state ?? "done") as StageState)
            }));
            scrollTo(stage, reduced);
          },
          onAgent: (event: AgentEvent) =>
            setRun((prev) => {
              const first = prev.agentEvents.length === 0;
              if (first) {
                const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                window.setTimeout(() => scrollTo("agents", reduced), 0);
              }
              return {
                ...prev,
                agentEvents: [...prev.agentEvents, event],
                elapsedMs: event.elapsedMs,
                stages: advanceTo(prev.stages, "agents", "running" as StageState)
              };
            }),
          onScreen: (payload, elapsedMs) => {
            setRun((prev) => ({ ...prev, serverMs: elapsedMs, elapsedMs }));
            unpack(payload);
          },
          onFailed: fail,
          onEnd: () => undefined
        },
        controller.signal
      ).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        fail(String(reason));
      });
    },
    [clearTimers, unpack]
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    clearTimers();
    setRun(EMPTY_RUN);
  }, [clearTimers]);

  return { run, start, stop, skip };
}
