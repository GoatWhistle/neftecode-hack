import { useEffect, useRef, useState } from "react";

const STEP_MS = 340;

export function useTrace(total: number, active: boolean): number {
  const [shown, setShown] = useState(active ? 0 : total);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    for (const id of timers.current) window.clearTimeout(id);
    timers.current = [];

    if (!active) {
      setShown(total);
      return;
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(total);
      return;
    }

    setShown(0);
    for (let position = 1; position <= total; position += 1) {
      const at = window.setTimeout(() => setShown(position), STEP_MS * position);
      timers.current.push(at);
    }

    return () => {
      for (const id of timers.current) window.clearTimeout(id);
      timers.current = [];
    };
  }, [total, active]);

  return shown;
}
