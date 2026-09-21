import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { duration } from "../format";
import { ORDER } from "../run/sequence";
import { STATE_WORD } from "../run/railStatus";
import type { RunState, StageSource, StageState } from "../run/types";
import { nodeById } from "./graph";
import { StageBody } from "./StageBody";

export const SOURCE_TEXT: Record<StageSource, string> = {
  server: "отметка сервера",
  payload: "раскрыт из payload — это не длительность расчёта этапа"
};

export interface DrawerProps {
  id: string;
  panelId: string;
  run: RunState;
  state: StageState;
  onClose: () => void;
  focusOnMount?: boolean;
  inert?: boolean;
  body?: ReactNode;
  meta?: string;
  closeLabel?: string;
}

function timeText(ms: number | null): string | null {
  if (ms === null) return null;
  return ms < 100 ? "<0,1 с" : `${duration(ms)} с`;
}

function startedAtOf(run: RunState, id: string): number | null {
  const position = ORDER.indexOf(id);
  if (position === -1) return null;
  if (position === 0) return 0;
  return run.stageAt[ORDER[position - 1] as string] ?? null;
}

export function Drawer({
  id,
  panelId,
  run,
  state,
  onClose,
  focusOnMount = true,
  inert = false,
  body,
  meta,
  closeLabel = "Закрыть панель этапа"
}: DrawerProps) {
  const node = nodeById(id);
  const closeRef = useRef<HTMLButtonElement>(null);
  const startedAt = startedAtOf(run, id);
  const at = run.stageAt[id];
  const spent =
    startedAt !== null && at !== undefined && (state === "done" || state === "failed")
      ? Math.max(0, at - startedAt)
      : null;
  const source = run.stageSource[id];
  const sourceText = state === "done" && source ? SOURCE_TEXT[source] : null;

  useEffect(() => {
    if (!focusOnMount || inert) return;
    closeRef.current?.focus({ preventScroll: true });
  }, [id, focusOnMount, inert]);

  if (!node) return null;

  const parts: string[] = [STATE_WORD[state]];
  if (startedAt !== null && startedAt > 0) parts.push(`начат на ${duration(startedAt)} с`);
  const spentText = timeText(spent);
  if (spentText !== null) parts.push(`длился ${spentText}`);
  if (sourceText) parts.push(sourceText);
  const metaText = meta ?? parts.join(" · ");

  return (
    <div
      className="drawer"
      id={panelId}
      role="region"
      aria-label={`Этап ${node.order}: ${node.label}`}
      aria-hidden={inert || undefined}
      inert={inert}
    >
      <div className="drawer__inner">
        <header className="drawer__head">
          <h2 className="drawer__title">
            <span className="drawer__order">{node.order}</span>
            <span className="drawer__sep" aria-hidden="true">·</span>
            <span className="drawer__name">{node.label}</span>
          </h2>
          <p className="drawer__meta">{metaText}</p>
          <button type="button" className="drawer__close" onClick={onClose} ref={closeRef}
            aria-label={closeLabel}>
            <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M3.5 3.5 L12.5 12.5 M12.5 3.5 L3.5 12.5" />
            </svg>
          </button>
        </header>
        {body ?? (
          <StageBody
            id={id}
            index={node.order ?? 0}
            state={state}
            payload={run.payload}
            facts={run.stageFacts[id]}
            agentEvents={run.agentEvents}
            elapsedMs={run.elapsedMs}
            lastFrameAt={run.lastFrameAt}
          />
        )}
      </div>
    </div>
  );
}
