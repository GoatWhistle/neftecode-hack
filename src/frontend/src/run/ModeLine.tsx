import { modeOf } from "./mode";
import type { RunState } from "./types";

export interface ModeLineProps {
  run: RunState;
}

export function ModeLine({ run }: ModeLineProps) {
  const mode = modeOf(run);
  if (mode === null) return null;
  return (
    <p className={`modeline modeline--${mode.kind}`}>
      <span className="modeline__word">режим</span>
      <span className="modeline__value">{mode.text}</span>
      {mode.detail ? <span className="modeline__detail">{mode.detail}</span> : null}
    </p>
  );
}
