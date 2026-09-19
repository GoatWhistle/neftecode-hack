import { useEffect } from "react";
import { STAGES } from "./stages";
import type { RunState } from "./run/types";

const BRAND = "CUTPOINT";

export function titleOf(run: RunState): string {
  if (run.status === "failed") return `Сбой прогона — ${BRAND}`;
  if (run.status === "running") {
    const done = STAGES.filter((stage) => run.stages[stage.id] === "done").length;
    const step = Math.min(done + 1, STAGES.length);
    return `Этап ${step} из ${STAGES.length} — ${BRAND}`;
  }
  const payload = run.payload;
  if (!payload) return BRAND;
  if (payload.decision.status === "refuse") return `Отказ — ${BRAND}`;
  return `${payload.status_label} — ${BRAND}`;
}

export function useDocumentTitle(run: RunState): void {
  useEffect(() => {
    document.title = titleOf(run);
  }, [run]);
}
