const KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
  "Spacebar"
]);

const VISIBLE_SHARE = 0.6;

let taken = false;
let listening = false;
let notify: ((taken: boolean) => void) | null = null;

function take(): void {
  if (taken) return;
  taken = true;
  notify?.(true);
}

function onWheel(): void {
  take();
}

function onTouch(): void {
  take();
}

function onKey(event: KeyboardEvent): void {
  const node = event.target as HTMLElement | null;
  const tag = node?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (KEYS.has(event.key)) take();
}

export function watchTakeover(onChange: (taken: boolean) => void): () => void {
  notify = onChange;
  if (!listening) {
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchstart", onTouch, { passive: true });
    window.addEventListener("keydown", onKey, { passive: true });
    listening = true;
  }
  return () => {
    if (!listening) return;
    window.removeEventListener("wheel", onWheel);
    window.removeEventListener("touchstart", onTouch);
    window.removeEventListener("keydown", onKey);
    listening = false;
    notify = null;
  };
}

export function releaseTakeover(): void {
  if (!taken) return;
  taken = false;
  notify?.(false);
}

export function isTakenOver(): boolean {
  return taken;
}

export function alreadyInView(node: Element): boolean {
  const top = node.getBoundingClientRect().top;
  return top >= 0 && top <= window.innerHeight * VISIBLE_SHARE;
}

export function scrollTo(id: string, reduced: boolean): void {
  if (taken) return;
  const node = document.getElementById(id);
  if (!node) return;
  if (alreadyInView(node)) return;
  node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

export function scrollToDirect(id: string, behavior: ScrollBehavior): void {
  const node = document.getElementById(id);
  if (!node) return;
  node.scrollIntoView({ behavior, block: "start" });
}
