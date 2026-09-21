import type { ScreenPayload } from "../types";
import { ORDER, stageRan } from "./sequence";
import type { RunState, StageState } from "./types";

export const STAGE_TITLE: Record<string, string> = {
  state: "Состояние",
  trust: "Доверие к данным",
  candidates: "Кандидаты",
  forecast: "Прогноз",
  choice: "Выбор",
  gate: "Gate",
  agents: "Агенты",
  decision: "Решение"
};

export interface StageOutcome {
  id: string;
  title: string;
  state: StageState;
}

export interface RunProgress {
  headline: string;
  ran: StageOutcome[];
  skipped: StageOutcome[];
  failed: StageOutcome[];
}

function classify(run: RunState, payload: ScreenPayload | null): StageOutcome[] {
  return ORDER.map((id) => {
    const held = run.stages[id] ?? "pending";
    let state: StageState = held;
    if (payload && held !== "failed" && held !== "running") {
      state = stageRan(id, payload) ? "done" : "skipped";
    }
    return { id, title: STAGE_TITLE[id] ?? id, state };
  });
}

function skippedHeadline(skipped: StageOutcome[]): string {
  if (skipped.length === 0) return "Расчёт завершён · все этапы выполнены";
  const names = skipped.map((item) => item.title.toLowerCase()).join(", ");
  return `Расчёт завершён · не запускались: ${names}`;
}

export function runProgress(run: RunState, payload: ScreenPayload | null): RunProgress {
  const all = classify(run, payload);
  const ran = all.filter((item) => item.state === "done");
  const skipped = all.filter((item) => item.state === "skipped");
  const failed = all.filter((item) => item.state === "failed");
  if (failed.length > 0) {
    const names = failed.map((item) => item.title.toLowerCase()).join(", ");
    return { headline: `Расчёт не завершён · обрыв на этапе: ${names}`, ran, skipped, failed };
  }
  if (run.status === "running") {
    const running = all.find((item) => item.state === "running");
    return {
      headline: running ? `Идёт расчёт · этап «${running.title}»` : "Идёт расчёт",
      ran,
      skipped,
      failed
    };
  }
  if (!payload) return { headline: "Результата нет", ran, skipped, failed };
  return { headline: skippedHeadline(skipped), ran, skipped, failed };
}
