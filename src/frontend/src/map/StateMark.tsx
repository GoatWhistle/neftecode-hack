import type { StageState } from "../run/types";
import { STATE_WORD } from "../run/railStatus";

export interface StateMarkProps {
  state: StageState;
}

const PATHS: Partial<Record<StageState, string>> = {
  pending: "M8 2.6 A5.4 5.4 0 1 1 8 13.4 A5.4 5.4 0 1 1 8 2.6",
  running: "M8 4.2 V8 L11 9.9",
  done: "M2.6 8.4 L6.4 12.4 L13.4 4.2",
  skipped: "M2.6 8 H13.4"
};

export function StateMark({ state }: StateMarkProps) {
  const word = STATE_WORD[state];
  const path = PATHS[state];
  if (path === undefined) return <span className="mapnode__word">{word}</span>;
  return (
    <span className={`mapnode__word mapnode__word--icon mapnode__word--${state}`} title={word}>
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {state === "running" ? <circle cx="8" cy="8" r="5.4" /> : null}
        <path d={path} />
      </svg>
    </span>
  );
}
