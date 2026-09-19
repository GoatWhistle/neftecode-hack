import { useEffect, useRef, useState } from "react";

const STEP_MS = 100;

export function useLiveClock(baseMs: number, sinceFrame: number | null, running: boolean): number {
  const [shown, setShown] = useState(baseMs);
  const peak = useRef(baseMs);

  useEffect(() => {
    if (!running) {
      peak.current = baseMs;
      setShown(baseMs);
      return;
    }
    const tick = (): void => {
      const drift = sinceFrame === null ? 0 : Math.max(0, performance.now() - sinceFrame);
      const next = Math.max(peak.current, baseMs + drift);
      peak.current = next;
      setShown(next);
    };
    tick();
    const timer = window.setInterval(tick, STEP_MS);
    return () => window.clearInterval(timer);
  }, [baseMs, sinceFrame, running]);

  return shown;
}
