import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ScreenPayload } from "../types";
import { streamDecision } from "./stream";
import type { AgentEvent, RunPhase, RunState, StageState } from "./types";
import { EMPTY_RUN } from "./types";
import { advanceTo, chainTo, LATE_STAGES, mergeFacts, mergePhase } from "./sequence";
import { createRevealQueue } from "./revealQueue";
import { releaseTakeover, scrollTo, watchTakeover } from "./autoscroll";

function readable(reason: unknown): string {
  if (reason instanceof DOMException && reason.name === "AbortError") return "прогон остановлен";
  if (reason instanceof TypeError) return "сервер недоступен, проверьте, что бэкенд запущен";
  if (reason instanceof Error) return reason.message;
  return String(reason);
}

function reducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export interface RunControls {
  run: RunState;
  start: (query: string) => void;
  stop: () => void;
  pending: boolean;
  followsUser: boolean;
  resumeFollow: () => void;
}

export function useRun(): RunControls {
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const [pending, setPending] = useState(false);
  const [followsUser, setFollowsUser] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const states = useRef<Record<string, StageState>>({});
  const queued = useRef<Record<string, StageState>>({});

  const reveal = useMemo(
    () =>
      createRevealQueue((id: string) => {
        const state = states.current[id] ?? "done";
        setRun((prev) => ({ ...prev, stages: advanceTo(prev.stages, id, state) }));
        scrollTo(id, reducedMotion());
      }),
    []
  );

  useEffect(() => {
    const drop = watchTakeover((taken) => setFollowsUser(taken));
    return () => {
      abort.current?.abort();
      reveal.clear();
      drop();
    };
  }, [reveal]);

  const resumeFollow = useCallback(() => {
    releaseTakeover();
    setFollowsUser(false);
  }, []);

  const enqueue = useCallback(
    (id: string, state: StageState) => {
      for (const step of chainTo(queued.current, id)) {
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
        for (const id of ["agents", ...LATE_STAGES]) {
          if (sources[id] === undefined) sources[id] = "payload";
        }
        return { ...prev, payload, stageSource: sources };
      });
      enqueue("agents", "done");
      for (const id of LATE_STAGES) enqueue(id, "done");
      reveal.onDrained(() =>
        setRun((prev) => (prev.status === "running" ? { ...prev, status: "done" } : prev))
      );
    },
    [enqueue, reveal]
  );

  const start = useCallback(
    (query: string) => {
      abort.current?.abort();
      reveal.clear();
      states.current = {};
      queued.current = {};
      releaseTakeover();
      setFollowsUser(false);
      setPending(true);
      const controller = new AbortController();
      abort.current = controller;
      setRun({ ...EMPTY_RUN, status: "running" });
      const fail = (message: string): void => {
        reveal.clear();
        setPending(false);
        setRun((prev) => ({
          ...prev,
          status: "failed",
          error: message,
          stages: { ...prev.stages, agents: "failed" as StageState }
        }));
      };

      streamDecision(
        query,
        {
          onPhase: (event) => {
            setPending(false);
            setRun((prev) => {
              const phases: RunPhase[] = mergePhase(prev.phases, event);
              return { ...prev, phases, elapsedMs: event.elapsed_ms };
            });
          },
          onTick: (elapsedMs) => setRun((prev) => ({ ...prev, elapsedMs })),
          onStage: (stage, elapsedMs, state, facts) => {
            setPending(false);
            setRun((prev) => ({
              ...prev,
              elapsedMs,
              stageFacts: mergeFacts(prev.stageFacts, stage, facts),
              stageSource: { ...prev.stageSource, [stage]: "server" }
            }));
            enqueue(stage, (state ?? "done") as StageState);
          },
          onAgent: (event: AgentEvent) => {
            setPending(false);
            setRun((prev) => ({
              ...prev,
              agentEvents: [...prev.agentEvents, event],
              elapsedMs: event.elapsedMs
            }));
            enqueue("agents", "running");
          },
          onScreen: (payload, elapsedMs) => {
            setPending(false);
            setRun((prev) => ({ ...prev, serverMs: elapsedMs, elapsedMs }));
            unpack(payload);
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

  const stop = useCallback(() => {
    abort.current?.abort();
    reveal.clear();
    states.current = {};
    queued.current = {};
    releaseTakeover();
    setFollowsUser(false);
    setPending(false);
    setRun(EMPTY_RUN);
  }, [reveal]);

  return { run, start, stop, pending, followsUser, resumeFollow };
}
