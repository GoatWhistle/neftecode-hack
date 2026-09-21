import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ScreenPayload } from "../types";
import type { StreamHandlers } from "./stream";
import { streamDecision } from "./stream";
import type { AgentEvent, RunPhase, RunState, StageState } from "./types";
import { EMPTY_RUN } from "./types";
import { advanceTo, chainTo, LATE_STAGES, mergeFacts, mergePhase, ORDER, stageRan } from "./sequence";
import { createRevealQueue } from "./revealQueue";
import type { RunTape } from "./replay";
import { canReplay, createTapeRecorder, playTape } from "./replay";

function readable(reason: unknown): string {
  if (reason instanceof DOMException && reason.name === "AbortError") return "прогон остановлен";
  if (reason instanceof TypeError) return "сервер недоступен, проверьте, что бэкенд запущен";
  if (reason instanceof Error) return reason.message;
  return String(reason);
}

export interface RunControls {
  run: RunState;
  start: (query: string) => void;
  stop: () => void;
  reset: () => void;
  replay: () => void;
  canReplay: boolean;
  replaying: boolean;
  pending: boolean;
}

export function useRun(): RunControls {
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const [pending, setPending] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [hasTape, setHasTape] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const states = useRef<Record<string, StageState>>({});
  const queued = useRef<Record<string, StageState>>({});
  const recorder = useRef(createTapeRecorder());
  const tape = useRef<RunTape | null>(null);
  const lastQuery = useRef<string | null>(null);

  const reveal = useMemo(
    () =>
      createRevealQueue((id: string) => {
        const state = states.current[id] ?? "done";
        setRun((prev) => ({ ...prev, stages: advanceTo(prev.stages, id, state) }));
      }),
    []
  );

  useEffect(() => {
    return () => {
      abort.current?.abort();
      reveal.clear();
    };
  }, [reveal]);

  const enqueue = useCallback(
    (id: string, state: StageState) => {
      for (const step of chainTo(queued.current, id, state)) {
        const next = (step === id ? state : "done") as StageState;
        const held = queued.current[step];
        if (held === next) continue;
        if (held === "done" && next !== "done") continue;
        states.current[step] = next;
        queued.current[step] = next;
        reveal.push(step);
      }
    },
    [reveal]
  );

  const unpack = useCallback(
    (payload: ScreenPayload) => {
      setRun((prev) => {
        const sources = { ...prev.stageSource };
        for (const id of LATE_STAGES) {
          if (sources[id] === undefined) sources[id] = "payload";
        }
        return {
          ...prev,
          payload,
          stageSource: sources,
          status: prev.status === "running" ? "done" : prev.status
        };
      });
      for (const id of LATE_STAGES) enqueue(id, stageRan(id, payload) ? "done" : "skipped");
    },
    [enqueue]
  );

  const run_ = useCallback(
    (source: (handlers: StreamHandlers, signal: AbortSignal) => Promise<void>, live: boolean,
     query: string | null) => {
      abort.current?.abort();
      reveal.clear();
      states.current = {};
      queued.current = {};
      setPending(live);
      setReplaying(!live);
      if (live) recorder.current.reset();
      const controller = new AbortController();
      abort.current = controller;
      setRun({ ...EMPTY_RUN, status: "running", live, query });
      const fail = (message: string): void => {
        reveal.clear();
        setPending(false);
        setRun((prev) => {
          const order = ORDER.filter((id) => prev.stages[id] !== undefined);
          const broken =
            order.find((id) => prev.stages[id] === "running") ??
            [...order].reverse().find((id) => prev.stages[id] === "done") ??
            "agents";
          return {
            ...prev,
            status: "failed",
            error: message,
            stages: { ...prev.stages, [broken]: "failed" as StageState }
          };
        });
      };

      const tap = live ? recorder.current : null;

      source(
        {
          onPhase: (event) => {
            tap?.onPhase(event);
            setPending(false);
            setRun((prev) => {
              const phases: RunPhase[] = mergePhase(prev.phases, event);
              return { ...prev, phases, elapsedMs: event.elapsed_ms };
            });
          },
          onTick: (elapsedMs) => {
            tap?.onTick(elapsedMs);
            setRun((prev) => ({ ...prev, elapsedMs, lastFrameAt: performance.now() }));
          },
          onStage: (stage, elapsedMs, state, facts) => {
            tap?.onStage(stage, elapsedMs, state, facts);
            setPending(false);
            setRun((prev) => ({
              ...prev,
              elapsedMs,
              stageFacts: mergeFacts(prev.stageFacts, stage, facts),
              stageSource: { ...prev.stageSource, [stage]: "server" },
              stageAt: { ...prev.stageAt, [stage]: elapsedMs }
            }));
            enqueue(stage, (state ?? "done") as StageState);
          },
          onAgent: (event: AgentEvent) => {
            tap?.onAgent(event);
            setPending(false);
            setRun((prev) => ({
              ...prev,
              agentEvents: [...prev.agentEvents, event],
              elapsedMs: event.elapsedMs
            }));
            enqueue("agents", "running");
          },
          onScreen: (payload, elapsedMs) => {
            tap?.onScreen(payload, elapsedMs);
            setPending(false);
            setRun((prev) => ({ ...prev, serverMs: elapsedMs, elapsedMs }));
            unpack(payload);
            if (live) {
              tape.current = recorder.current.snapshot();
              setHasTape(true);
            }
          },
          onFailed: fail,
          onEnd: () => undefined
        },
        controller.signal
      ).catch((reason: unknown) => {
        if (controller.signal.aborted || abort.current !== controller) return;
        fail(readable(reason));
      });
    },
    [enqueue, reveal, unpack]
  );

  const start = useCallback(
    (query: string) => {
      lastQuery.current = query;
      run_((handlers, signal) => streamDecision(query, handlers, signal), true, query);
    },
    [run_]
  );

  const replay = useCallback(() => {
    if (!canReplay(tape.current)) return;
    const recorded = tape.current;
    const query = lastQuery.current;
    run_((handlers, signal) => playTape(recorded, handlers, signal), false, query);
  }, [run_]);

  const stop = useCallback(() => {
    abort.current?.abort();
    reveal.clear();
    states.current = {};
    queued.current = {};
    setPending(false);
    setReplaying(false);
    setRun((prev) =>
      prev.status === "running" ? { ...prev, status: "stopped" } : EMPTY_RUN
    );
  }, [reveal]);

  const reset = useCallback(() => {
    abort.current?.abort();
    reveal.clear();
    states.current = {};
    queued.current = {};
    setPending(false);
    setReplaying(false);
    setRun(EMPTY_RUN);
  }, [reveal]);

  return {
    run,
    start,
    stop,
    reset,
    replay,
    canReplay: hasTape,
    replaying,
    pending
  };
}
