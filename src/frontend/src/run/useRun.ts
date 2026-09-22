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
import type { RecordInfo } from "./hydrate";
import { hydrateRun, recordInfoOf } from "./hydrate";
import type { RunRecord } from "./record";
import { buildRecord, tapeOf } from "./record";

const FIRST_STAGE = ORDER[0] as string;

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
  openRecord: (record: RunRecord, exportedAt: string | null) => void;
  adopt: (record: RunRecord) => void;
  tapeSnapshot: () => RunTape | null;
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
  /**
   * Единственный источник повтора: завершённая запись целиком (события, payload, query, дата,
   * provider, run_id, подпись). Новый live-прогон сбрасывает его до своего успешного завершения,
   * поэтому лента одного прогона не может быть показана под запросом другого.
   */
  const source = useRef<{ record: RunRecord; exportedAt: string | null } | null>(null);
  const setSource = useCallback((next: { record: RunRecord; exportedAt: string | null } | null) => {
    source.current = next;
    setHasTape(next !== null && canReplay(tapeOf(next.record)));
  }, []);

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
    (feed: (handlers: StreamHandlers, signal: AbortSignal) => Promise<void>, live: boolean,
     query: string | null, info: RecordInfo | null) => {
      abort.current?.abort();
      reveal.clear();
      states.current = {};
      queued.current = {};
      setPending(live);
      setReplaying(!live);
      if (live) recorder.current.reset();
      const controller = new AbortController();
      abort.current = controller;
      setRun({ ...EMPTY_RUN, status: "running", live, query, record: info });
      const fail = (message: string): void => {
        if (abort.current !== controller) return;
        reveal.clear();
        setPending(false);
        setRun((prev) => {
          const order = ORDER.filter((id) => prev.stages[id] !== undefined);
          const broken =
            order.find((id) => prev.stages[id] === "running") ??
            [...order].reverse().find((id) => prev.stages[id] === "done") ??
            FIRST_STAGE;
          return {
            ...prev,
            status: "failed",
            error: message,
            stages: { ...prev.stages, [broken]: "failed" as StageState }
          };
        });
      };

      const tap = live ? recorder.current : null;

      const stale = (): boolean => controller.signal.aborted || abort.current !== controller;

      feed(
        {
          onPhase: (event) => {
            if (stale()) return;
            tap?.onPhase(event);
            setPending(false);
            setRun((prev) => {
              const phases: RunPhase[] = mergePhase(prev.phases, event);
              return { ...prev, phases, elapsedMs: event.elapsed_ms };
            });
          },
          onTick: (elapsedMs) => {
            if (stale()) return;
            tap?.onTick(elapsedMs);
            setRun((prev) => ({ ...prev, elapsedMs, lastFrameAt: performance.now() }));
          },
          onStage: (stage, elapsedMs, state, facts) => {
            if (stale()) return;
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
          onCore: (core) => {
            if (stale()) return;
            tap?.onCore(core);
            setPending(false);
            setRun((prev) => ({ ...prev, core, elapsedMs: core.elapsedMs }));
          },
          onAgent: (event: AgentEvent) => {
            if (stale()) return;
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
            if (stale()) return;
            tap?.onScreen(payload, elapsedMs);
            setPending(false);
            setRun((prev) => ({ ...prev, serverMs: elapsedMs, elapsedMs }));
            unpack(payload);
            if (live) {
              // Запись этого прогона; App заменяет её полной (условия, подпись) через adopt.
              setSource({ record: buildRecord({ payload, form: null, query, label: "текущий прогон",
                tape: recorder.current.snapshot(), durationMs: elapsedMs }), exportedAt: null });
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
    [enqueue, reveal, unpack, setSource]
  );

  const start = useCallback(
    (query: string) => {
      setSource(null);
      run_((handlers, signal) => streamDecision(query, handlers, signal), true, query, null);
    },
    [run_, setSource]
  );

  const replay = useCallback(() => {
    const held = source.current;
    const recorded = held ? tapeOf(held.record) : null;
    if (!held || !canReplay(recorded)) return;
    run_((handlers, signal) => playTape(recorded, handlers, signal), false, held.record.query,
      recordInfoOf(held.record, held.exportedAt));
  }, [run_]);

  const adopt = useCallback((record: RunRecord) => setSource({ record, exportedAt: null }), [setSource]);

  const openRecord = useCallback(
    (record: RunRecord, exportedAt: string | null) => {
      const info = recordInfoOf(record, exportedAt);
      const restored = hydrateRun(record, info);
      abort.current?.abort();
      reveal.clear();
      states.current = {};
      queued.current = {};
      setPending(false);
      setReplaying(false);
      setSource({ record, exportedAt });
      setRun(restored);
    },
    [reveal, setSource]
  );

  const tapeSnapshot = useCallback(() => (source.current ? tapeOf(source.current.record) : null), []);

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
    setSource(null);
    setRun(EMPTY_RUN);
  }, [reveal, setSource]);

  return {
    run,
    start,
    stop,
    reset,
    replay,
    openRecord,
    adopt,
    tapeSnapshot,
    canReplay: hasTape,
    replaying,
    pending
  };
}
