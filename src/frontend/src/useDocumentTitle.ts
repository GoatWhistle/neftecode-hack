import { useEffect, useMemo } from "react";
import { STAGES } from "./stages";
import type { RunState } from "./run/types";

const BRAND = "CUTPOINT";

export function titleOf(run: RunState): string {
  if (run.status === "failed") return `Расчёт не завершён — ${BRAND}`;
  if (run.status === "stopped") return `Расчёт остановлен — ${BRAND}`;
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
  const title = useMemo(() => titleOf(run), [run]);
  useEffect(() => {
    document.title = title;
  }, [title]);
}
