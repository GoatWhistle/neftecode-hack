import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent } from "react";
import type { ScreenPayload } from "../types";
import { STAGES } from "../stages";
import type { RunState } from "../run/types";
import { stageStateOf } from "../run/types";
import { ORDER } from "../run/sequence";
import { scrollToDirect } from "../run/autoscroll";
import { railSignal } from "../run/railStatus";
import { LampDot } from "./Primitives";
import { RailOrder } from "./RailOrder";

const FAR_GAP = 3;

function seconds(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  return `${(ms / 1000).toFixed(1).replace(".", ",")} с`;
}

export interface RailProps {
  payload: ScreenPayload | null;
  active: string;
  run: RunState;
  onNavigate?: () => void;
}

function indexOf(id: string): number {
  return id === "config" ? -1 : ORDER.indexOf(id);
}

export function Rail({ payload, active, run, onNavigate }: RailProps) {
  const listRef = useRef<HTMLOListElement>(null);

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
      scrollToDirect(id, reduced || far ? "auto" : "smooth");
      onNavigate?.();
    },
    [active, onNavigate]
  );

  return (
    <aside className="rail rail--enter" aria-label="Ход прогона">
      {run.status === "running" ? (
        <p className="rail__clock" aria-hidden="true">
          <span className="rail__clock-word">идёт</span>
          <span className="rail__clock-value">{seconds(run.elapsedMs)}</span>
        </p>
      ) : null}
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
              <span className="rail__note">приняты</span>
            </span>
          </a>
        </li>
        {STAGES.map((stage, position) => {
          const state = stageStateOf(run, stage.id);
          const isActive = active === stage.id;
          const signal = railSignal(run, payload, stage.id);
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
                  <span className={`rail__note rail__note--${signal.lamp}`}>{signal.note}</span>
                </span>
                {signal.live ? <LampDot state={signal.lamp} /> : null}
              </a>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
