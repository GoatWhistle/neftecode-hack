export const REVEAL_GAP_MS = 450;

export interface RevealQueue {
  push: (id: string) => void;
  flush: () => void;
  clear: () => void;
}

function reducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function createRevealQueue(emit: (id: string) => void): RevealQueue {
  const pending: string[] = [];
  let timer: number | null = null;
  let lastAt = 0;

  const release = (): void => {
    timer = null;
    const id = pending.shift();
    if (id === undefined) return;
    lastAt = performance.now();
    emit(id);
    schedule();
  };

  const schedule = (): void => {
    if (timer !== null || pending.length === 0) return;
    const gap = reducedMotion() ? 0 : REVEAL_GAP_MS;
    const wait = Math.max(0, gap - (performance.now() - lastAt));
    if (wait === 0) {
      release();
      return;
    }
    timer = window.setTimeout(release, wait);
  };

  const clear = (): void => {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    pending.length = 0;
    lastAt = 0;
  };

  return {
    push: (id: string) => {
      if (pending.includes(id)) return;
      pending.push(id);
      schedule();
    },
    flush: () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      const rest = pending.splice(0, pending.length);
      for (const id of rest) emit(id);
      lastAt = performance.now();
    },
    clear
  };
}
