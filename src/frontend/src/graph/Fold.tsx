import type { ReactNode } from "react";
import type { Agentic } from "../types";

export interface FoldProps {
  title: string;
  hint?: string;
  children: ReactNode;
}

export function Fold({ title, hint, children }: FoldProps) {
  return (
    <details className="fold">
      <summary className="fold__head">
        <span className="fold__mark" aria-hidden="true" />
        <span className="fold__title">{title}</span>
        {hint === undefined ? null : <span className="fold__hint">{hint}</span>}
      </summary>
      <div className="fold__body">{children}</div>
    </details>
  );
}

const MODE_HINT: Record<string, string> = {
  selected: "агенты выбрали план",
  confirmed_legacy: "агенты подтвердили детерминированный план",
  refused: "агенты дошли до отказа",
  fallback: "живая модель не работала",
  skipped: "агенты не привлекались"
};

export function modeHint(agentic: Agentic | null): string {
  if (agentic === null) return "режим не передавался";
  const word = MODE_HINT[agentic.outcome] ?? agentic.outcome;
  const who = agentic.deterministic_policy === true
    ? "детерминированная политика"
    : agentic.model ?? "модель не названа";
  return `${word} · ${who}`;
}
