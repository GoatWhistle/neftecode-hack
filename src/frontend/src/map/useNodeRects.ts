import { useCallback, useEffect, useRef, useState } from "react";

export interface NodeRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface NodeRects {
  rects: Record<string, NodeRect>;
  width: number;
  height: number;
}

const EMPTY: NodeRects = { rects: {}, width: 0, height: 0 };

function sameRect(a: NodeRect | undefined, b: NodeRect): boolean {
  if (!a) return false;
  return (
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.width - b.width) < 0.5 &&
    Math.abs(a.height - b.height) < 0.5
  );
}

function sameMap(a: NodeRects, b: NodeRects): boolean {
  if (Math.abs(a.width - b.width) >= 0.5 || Math.abs(a.height - b.height) >= 0.5) return false;
  const keysA = Object.keys(a.rects);
  const keysB = Object.keys(b.rects);
  if (keysA.length !== keysB.length) return false;
  return keysB.every((key) => sameRect(a.rects[key], b.rects[key] as NodeRect));
}

export function useNodeRects(container: HTMLElement | null): NodeRects {
  const [measured, setMeasured] = useState<NodeRects>(EMPTY);
  const frame = useRef<number | null>(null);
  const latest = useRef<NodeRects>(EMPTY);

  const measure = useCallback(() => {
    frame.current = null;
    if (!container) return;
    const base = container.getBoundingClientRect();
    const next: NodeRects = { rects: {}, width: base.width, height: base.height };
    const found = container.querySelectorAll<HTMLElement>("[data-map-node]");
    found.forEach((element) => {
      const id = element.dataset["mapNode"];
      if (!id) return;
      const box = element.getBoundingClientRect();
      next.rects[id] = {
        left: box.left - base.left,
        top: box.top - base.top,
        width: box.width,
        height: box.height
      };
    });
    if (sameMap(latest.current, next)) return;
    latest.current = next;
    setMeasured(next);
  }, [container]);

  const schedule = useCallback(() => {
    if (frame.current !== null) return;
    frame.current = window.requestAnimationFrame(measure);
  }, [measure]);

  useEffect(() => {
    if (!container) {
      latest.current = EMPTY;
      setMeasured(EMPTY);
      return;
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(container);
    container.querySelectorAll<HTMLElement>("[data-map-node]").forEach((element) => {
      observer.observe(element);
    });
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      if (frame.current !== null) window.cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [container, schedule]);

  return measured;
}
