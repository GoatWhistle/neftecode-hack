export function scrollToDrawer(panelId: string): void {
  const node = document.getElementById(panelId);
  if (!node) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
}
