import { useEffect, useRef, useState } from "react";
import { duration } from "../format";
import { STATE_WORD } from "../run/railStatus";
import { ORDER, reachedState } from "../run/sequence";
import type { RunState, StageState } from "../run/types";
import { useLiveClock } from "../useLiveClock";
import { nodeById } from "./graph";

const STALE_MS = 4000;

export const MAP_ANCHOR = "map-board";

function anchorOf(): HTMLElement | null {
  return document.getElementById(MAP_ANCHOR) ?? document.querySelector<HTMLElement>(".map__board");
}

export interface StatusBarProps {
  run: RunState;
  onStop: () => void;
  onReplay?: () => void;
  canReplay?: boolean;
}

interface Current {
  id: string;
  state: StageState;
}

function currentOf(run: RunState): Current | null {
  if (run.status === "idle") return null;
  const running = ORDER.find((id) => reachedState(run.stages, id) === "running");
  if (running) return { id: running, state: "running" };
  const failed = ORDER.find((id) => reachedState(run.stages, id) === "failed");
  if (failed) return { id: failed, state: "failed" };
  const last = [...ORDER].reverse().find((id) => {
    const state = reachedState(run.stages, id);
    return state === "done" || state === "skipped";
  });
  return last ? { id: last, state: reachedState(run.stages, last) } : null;
}

function useAway(active: boolean): boolean {
  const [away, setAway] = useState(false);
  useEffect(() => {
    if (!active) {
      setAway(false);
      return;
    }
    let frame: number | null = null;
    const read = (): void => {
      frame = null;
      const anchor = anchorOf();
      setAway(anchor ? anchor.getBoundingClientRect().top < 0 : false);
    };
    const schedule = (): void => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(read);
    };
    read();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [active]);
  return away;
}

function useSilence(lastFrameAt: number | null, running: boolean): number | null {
  const [held, setHeld] = useState<number | null>(null);
  const frame = useRef(lastFrameAt);
  frame.current = lastFrameAt;
  useEffect(() => {
    if (!running) {
      setHeld(null);
      return;
    }
    const tick = (): void => {
      const at = frame.current;
      setHeld(at === null ? null : Math.max(0, performance.now() - at));
    };
    tick();
    const timer = window.setInterval(tick, 200);
    return () => window.clearInterval(timer);
  }, [running]);
  return held;
}

export function StatusBar({ run, onStop, onReplay, canReplay }: StatusBarProps) {
  const away = useAway(run.status !== "idle");
  const running = run.status === "running";
  const liveMs = useLiveClock(run.elapsedMs, run.lastFrameAt, running && run.live);
  const silence = useSilence(run.lastFrameAt, running && run.live);
  const current = currentOf(run);
  const node = current ? nodeById(current.id) : null;
  const stale = running && silence !== null && silence >= STALE_MS;
  const showReplay = !running && canReplay === true && onReplay !== undefined;

  if (run.status === "idle" || !away) return null;

  const toMap = (): void => {
    const anchor = anchorOf();
    if (!anchor) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    anchor.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  };

  return (
    <div className="statusbar" role="status">
      <p className="statusbar__clock">
        {running && node && current?.state === "running" ? null : (
          <span className="statusbar__word">{running ? "идёт" : "всего"}</span>
        )}
        <span className="statusbar__value">
          {duration(running ? liveMs : (run.serverMs ?? run.elapsedMs))}
        </span>
      </p>
      {node && current ? (
        <p className={`statusbar__stage statusbar__stage--${current.state}`}>
          <span className="statusbar__order">{String(node.order ?? 0).padStart(2, "0")}</span>
          <span className="statusbar__name">{node.label}</span>
          <span className="statusbar__state">{STATE_WORD[current.state]}</span>
        </p>
      ) : null}
      {stale ? (
        <p className="statusbar__stale">
          последний ответ сервера {duration(silence ?? 0)} назад
        </p>
      ) : null}
      {!run.live ? (
        <p className="statusbar__stale">повтор записи, паузы сжаты</p>
      ) : null}
      <span className="statusbar__gap" />
      <button
        type="button"
        className="statusbar__button statusbar__button--icon"
        onClick={toMap}
        aria-label="Перейти к схеме"
        title="К схеме"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M8 13 V3.4 M3.8 7.6 L8 3.2 L12.2 7.6" />
        </svg>
      </button>
      {showReplay ? (
        <button type="button" className="statusbar__button" onClick={onReplay}>
          ▶ Ещё раз
        </button>
      ) : null}
      {running ? (
        <button
          type="button"
          className="statusbar__button statusbar__button--icon statusbar__button--stop"
          onClick={onStop}
          aria-label="Остановить прогон"
          title="Стоп · то же самое делает клавиша Escape"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <rect x="4.4" y="4.4" width="7.2" height="7.2" rx="1" />
          </svg>
        </button>
      ) : null}
    </div>
  );
}
