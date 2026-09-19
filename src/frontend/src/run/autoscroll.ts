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

const BOTTOM_SLACK = 160;
const STICK_STEP_MS = 120;

let taken = false;
let listening = false;
let sticking = false;
let stickTimer: number | null = null;
let lastTarget = 0;
let notify: ((taken: boolean) => void) | null = null;

export function takeOver(): void {
  take();
}

function take(): void {
  if (taken) return;
  taken = true;
  notify?.(true);
}

function atBottom(): boolean {
  const scrolled = window.scrollY + window.innerHeight;
  return document.documentElement.scrollHeight - scrolled <= BOTTOM_SLACK;
}

function toBottom(): void {
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
}

function pulse(): void {
  if (taken || !sticking) return;
  const target = document.documentElement.scrollHeight;
  if (target === lastTarget && atBottom()) return;
  lastTarget = target;
  toBottom();
}

export function startSticking(): void {
  sticking = true;
  lastTarget = 0;
  if (stickTimer !== null) return;
  stickTimer = window.setInterval(pulse, STICK_STEP_MS);
}

export function stopSticking(): void {
  sticking = false;
  if (stickTimer === null) return;
  window.clearInterval(stickTimer);
  stickTimer = null;
}

function onWheel(event: WheelEvent): void {
  if (event.deltaY > 0 && atBottom()) {
    releaseTakeover();
    return;
  }
  take();
}

function onTouch(): void {
  take();
}

function onScroll(): void {
  if (taken && atBottom()) releaseTakeover();
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
    window.addEventListener("scroll", onScroll, { passive: true });
    listening = true;
  }
  return () => {
    if (!listening) return;
    window.removeEventListener("wheel", onWheel);
    window.removeEventListener("touchstart", onTouch);
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("scroll", onScroll);
    listening = false;
    notify = null;
    stopSticking();
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

export function scrollToDirect(id: string, behavior: ScrollBehavior): void {
  const node = document.getElementById(id);
  if (!node) return;
  node.scrollIntoView({ behavior, block: "start" });
}
