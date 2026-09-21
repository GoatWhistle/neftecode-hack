import { useEffect, useState } from "react";
import { ORDER } from "../run/sequence";
import type { RunState, StageState } from "../run/types";
import { SUMMARY_ID } from "./Summary";

export function spentOf(run: RunState, id: string, state: StageState, liveMs: number): number | null {
  const position = ORDER.indexOf(id);
  if (position === -1) return null;
  const startedAt = position === 0 ? 0 : (run.stageAt[ORDER[position - 1] as string] ?? 0);
  if (state === "running") return Math.max(0, liveMs - startedAt);
  const at = run.stageAt[id];
  if ((state === "done" || state === "failed") && at !== undefined) {
    return Math.max(0, at - startedAt);
  }
  return null;
}

export function instant(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function focusNode(board: HTMLElement, id: string): void {
  const target = board.querySelector<HTMLElement>(`[data-map-node="${id}"]`);
  target?.focus();
}

export const AFTER_ID = "after";

function scrollTo(node: HTMLElement | null): void {
  if (!node) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

export function scrollToSummary(): void {
  scrollTo(document.getElementById(AFTER_ID) ?? document.getElementById(SUMMARY_ID));
}

export function scrollToMap(): void {
  window.requestAnimationFrame(() => {
    scrollTo(document.querySelector<HTMLElement>(".map__board"));
  });
}

export function scrollToConditions(): void {
  window.requestAnimationFrame(() => {
    scrollTo(document.getElementById("map-drawer-input"));
  });
}

export function usePrinting(): boolean {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("print");
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => setPrinting(event.matches);
    const onBefore = () => setPrinting(true);
    const onAfter = () => setPrinting(false);
    query.addEventListener("change", onChange);
    window.addEventListener("beforeprint", onBefore);
    window.addEventListener("afterprint", onAfter);
    return () => {
      query.removeEventListener("change", onChange);
      window.removeEventListener("beforeprint", onBefore);
      window.removeEventListener("afterprint", onAfter);
    };
  }, []);
  return printing;
}
