import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent } from "react";
import type { ScreenPayload } from "../types";
import { STAGES } from "../stages";
import { duration } from "../format";
import type { RunState } from "../run/types";
import { ORDER, reachedState } from "../run/sequence";
import { scrollToDirect, takeOver } from "../run/autoscroll";
import { pinStage } from "../useActiveStage";
import { useLiveClock } from "../useLiveClock";
import { RailOrder } from "./RailOrder";

const FAR_GAP = 3;

export interface RailProps {
  payload: ScreenPayload | null;
  active: string;
  run: RunState;
  onNavigate?: () => void;
}

function indexOf(id: string): number {
  return id === "config" ? -1 : ORDER.indexOf(id);
}

export function Rail({ active, run, onNavigate }: RailProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const liveMs = useLiveClock(run.elapsedMs, run.lastFrameAt, run.status === "running");

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    if (list.scrollWidth <= list.clientWidth + 1) return;
    const current = list.querySelector<HTMLElement>("[aria-current]");
    if (!current) return;
    const target = current.offsetLeft - (list.clientWidth - current.offsetWidth) / 2;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ left: Math.max(0, target), behavior: reduced ? "auto" : "smooth" });
  }, [active]);

  const jump = useCallback(
    (event: MouseEvent<HTMLAnchorElement>, id: string) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const far = Math.abs(indexOf(id) - indexOf(active)) > FAR_GAP;
      takeOver();
      pinStage(id);
      scrollToDirect(id, reduced || far ? "auto" : "smooth");
      onNavigate?.();
    },
    [active, onNavigate]
  );

  return (
    <aside className="rail rail--enter" aria-label="Ход прогона">
      <ol className="rail__list" ref={listRef}>
        <li className={`rail__item rail__item--done ${active === "config" ? "rail__item--active" : ""}`}>
          <a
            className="rail__link"
            href="#config"
            aria-current={active === "config" ? "step" : undefined}
            onClick={(event) => jump(event, "config")}
          >
            <span className="rail__cursor" aria-hidden="true" />
            <RailOrder value={0} state="done" />
            <span className="rail__label">
              <span className="rail__name">Условия</span>
            </span>
          </a>
        </li>
        {STAGES.map((stage, position) => {
          const state = reachedState(run.stages, stage.id);
          const startedAt = position === 0 ? 0 : (run.stageAt[ORDER[position - 1] as string] ?? 0);
          const at = run.stageAt[stage.id];
          const spent =
            state === "running"
              ? Math.max(0, liveMs - startedAt)
              : (state === "done" || state === "failed") && at !== undefined
                ? Math.max(0, at - startedAt)
                : null;
          const isActive = active === stage.id;
          return (
            <li
              key={stage.id}
              className={`rail__item rail__item--${state} ${isActive ? "rail__item--active" : ""}`}
              data-band={position + 1}
            >
              <a
                className="rail__link"
                href={`#${stage.id}`}
                aria-current={isActive ? "step" : undefined}
                onClick={(event) => jump(event, stage.id)}
              >
                <span className="rail__cursor" aria-hidden="true" />
                <RailOrder value={position + 1} state={state} />
                <span className="rail__label">
                  <span className="rail__name">{stage.label}</span>
                </span>
                {spent !== null ? (
                  <span className="rail__at">
                    {state !== "running" && spent < 100 ? "<0,1" : duration(spent)}
                  </span>
                ) : null}
              </a>
            </li>
          );
        })}
      </ol>
      {run.status === "idle" ? null : (
        <p className="rail__clock" aria-hidden="true">
          <span className="rail__clock-word">{run.status === "running" ? "идёт" : "всего"}</span>
          <span className="rail__clock-value">
            {duration(run.status === "running" ? liveMs : (run.serverMs ?? run.elapsedMs))}
          </span>
        </p>
      )}
    </aside>
  );
}
