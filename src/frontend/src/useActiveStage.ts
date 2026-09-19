import { useEffect, useState } from "react";
import { STAGES } from "./stages";

const IDS = ["config", ...STAGES.map((stage) => stage.id)];

let pinned: string | null = null;
let pinnedUntil = 0;

export function pinStage(id: string, ms = 900): void {
  pinned = id;
  pinnedUntil = performance.now() + ms;
}

function currentId(): string | null {
  if (pinned !== null && performance.now() < pinnedUntil) return pinned;
  const view = window.innerHeight;
  const line = 96;
  const doc = document.documentElement;
  const scrollable = doc.scrollHeight > view + 2;
  const bottom = scrollable && window.scrollY + view >= doc.scrollHeight - 2;
  let above: string | null = null;
  let seen: string | null = null;
  let last: string | null = null;
  for (const id of IDS) {
    const node = document.getElementById(id);
    if (!node) continue;
    const box = node.getBoundingClientRect();
    if (box.top <= line) above = id;
    if (box.top < view && box.bottom > 0) {
      if (seen === null) seen = id;
      last = id;
    }
  }
  if (bottom && last !== null) {
    const tail = IDS.indexOf(last);
    const head = above === null ? -1 : IDS.indexOf(above);
    if (tail > head && tail === IDS.length - 1) return last;
  }
  return above ?? seen;
}

export function useActiveStage(enabled: boolean): string {
  const [active, setActive] = useState<string>("config");

  useEffect(() => {
    if (!enabled) {
      setActive("config");
      return;
    }

    let frame = 0;
    const sync = (): void => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const id = currentId();
        if (id) setActive(id);
      });
    };

    const observer = new IntersectionObserver(sync, { threshold: 0 });
    const attach = (): void => {
      for (const id of IDS) {
        const node = document.getElementById(id);
        if (node) observer.observe(node);
      }
      sync();
    };
    attach();
    const retry = window.setTimeout(attach, 600);
    window.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);

    return () => {
      window.clearTimeout(retry);
      window.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      if (frame) window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [enabled]);

  return active;
}
