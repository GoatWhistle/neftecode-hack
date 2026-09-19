import type { ScreenPayload } from "./types";
import type { Lamp } from "./ui/Primitives";

export interface Stage {
  id: string;
  label: string;
  lamp: (payload: ScreenPayload) => Lamp;
}

function trustLamp(payload: ScreenPayload): Lamp {
  const event = (payload.decision.trace ?? []).find((item) => item.agent === "data");
  if (!event) return payload.sources?.length ? "pass" : "unknown";
  return event["usable"] === true ? "pass" : "fail";
}

function gateLamp(payload: ScreenPayload): Lamp {
  const checks = payload.decision.gate?.checks ?? [];
  if (checks.length === 0) return "unknown";
  if (checks.some((check) => check.status === "fail")) return "fail";
  if (checks.some((check) => check.status === "unknown")) return "unknown";
  return "pass";
}

function candidatesLamp(payload: ScreenPayload): Lamp {
  const event = (payload.decision.trace ?? []).find((item) => item.agent === "optimizer");
  if (!event) return "unknown";
  return payload.decision.selected_plan ? "pass" : "fail";
}

function agentsLamp(payload: ScreenPayload): Lamp {
  const trace = payload.decision.trace ?? [];
  if (trace.length === 0) return "unknown";
  const vetoed = trace.some((event) => ((event["vetoes"] as unknown[] | undefined)?.length ?? 0) > 0);
  return vetoed ? "fail" : "pass";
}

function forecastLamp(payload: ScreenPayload): Lamp {
  const checks = (payload.decision.gate?.checks ?? []).filter(
    (check) => check.constraint_id === "quality.sulfur_mgkg"
  );
  if (checks.length === 0) return "unknown";
  return checks.some((check) => check.status !== "pass") ? "fail" : "pass";
}

function decisionLamp(payload: ScreenPayload): Lamp {
  if (payload.decision.status === "refuse") return "fail";
  return (payload.explanation.warnings?.length ?? 0) > 0 ? "unknown" : "pass";
}

export const STAGES: readonly Stage[] = [
  { id: "state", label: "Состояние", lamp: (p) => (p.explanation.current_operation ? "pass" : "unknown") },
  { id: "trust", label: "Доверие к данным", lamp: trustLamp },
  { id: "forecast", label: "Прогноз", lamp: forecastLamp },
  { id: "candidates", label: "Кандидаты", lamp: candidatesLamp },
  { id: "gate", label: "Gate", lamp: gateLamp },
  { id: "agents", label: "Агенты", lamp: agentsLamp },
  { id: "choice", label: "Выбор", lamp: (p) => (p.decision.selected_plan ? "pass" : "fail") },
  { id: "decision", label: "Решение", lamp: decisionLamp }
];
