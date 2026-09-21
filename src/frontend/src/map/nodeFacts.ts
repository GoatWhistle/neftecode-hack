import type { ScreenPayload } from "../types";
import { duration } from "../format";
import { buildActs } from "../run/agentActs";
import { ROLE_TEXT } from "../run/agentMeters";
import { chronicle } from "../run/orchSteps";
import {
  candidateLines,
  choiceLines,
  forecastLines,
  gateLines,
  inventoryLines,
  trustSources,
  trustVerdict
} from "../run/stageFacts";
import type { FactLine } from "../run/stageFacts";
import type { AgentEvent, RunState, StageFacts } from "../run/types";

const AWAITED_ROLE: Record<string, string> = {
  quality: "агента качества",
  reliability: "агента надёжности"
};

function joinLines(lines: FactLine[]): string | null {
  if (lines.length === 0) return null;
  return lines
    .slice(0, 2)
    .map((line) => `${line.label} ${line.value}`)
    .join(" · ");
}

function stateCaption(id: string, facts: StageFacts | undefined): string | null {
  if (id === "state") return joinLines(inventoryLines(facts));
  if (id === "trust") {
    const sources = trustSources(facts);
    const verdict = trustVerdict(facts);
    if (verdict.length > 0) return joinLines(verdict);
    if (sources.length > 0) {
      const usable = sources.filter((source) => source.usable).length;
      return `источников ${sources.length} · годных ${usable}`;
    }
    return null;
  }
  if (id === "candidates") return joinLines(candidateLines(facts));
  if (id === "forecast") return joinLines(forecastLines(facts));
  if (id === "choice") return joinLines(choiceLines(facts));
  if (id === "gate") return joinLines(gateLines(facts));
  return null;
}

function waitingCaption(events: AgentEvent[], facts: StageFacts | undefined, liveMs: number): string | null {
  if (events.length === 0) return null;
  const acts = buildActs(events);
  const lastOrch = [...acts].reverse().find((act) => act.kind === "orchestrator");
  if (!lastOrch || lastOrch.kind !== "orchestrator") return `событий ${events.length}`;
  const chart = chronicle(lastOrch, facts);
  const move = chart.moves[chart.moves.length - 1];
  const step = move?.step ?? null;
  const limit = chart.limit;
  const stepText = step !== null ? `ход ${step}${limit !== null ? ` из ${limit}` : ""}` : null;

  const lastEvent = events[events.length - 1];
  if (lastEvent && (lastEvent.kind === "tool" || lastEvent.kind === "consult")) {
    const role = lastEvent.tool_name === "ask_reliability_agent"
      ? "reliability"
      : lastEvent.tool_name === "ask_quality_agent"
        ? "quality"
        : null;
    if (role) {
      const waitMs = Math.max(0, liveMs - lastEvent.elapsedMs);
      const waitText = waitMs >= 100 ? duration(waitMs) : "<0,1";
      return [stepText, `ждём ${AWAITED_ROLE[role] ?? ROLE_TEXT[role] ?? role} ${waitText}`]
        .filter(Boolean).join(" · ");
    }
  }
  if (lastEvent && lastEvent.kind === "llm_call") {
    const waitMs = Math.max(0, liveMs - lastEvent.elapsedMs);
    const waitText = waitMs >= 100 ? duration(waitMs) : "<0,1";
    return [stepText, `ждём модель ${waitText}`].filter(Boolean).join(" · ");
  }
  return stepText ?? `событий ${events.length}`;
}

function decisionCaption(payload: ScreenPayload | null): string | null {
  if (!payload) return null;
  const label = payload.status_label;
  const plan = payload.decision.selected_plan?.plan_id;
  return [label, plan ? `план ${plan}` : null].filter(Boolean).join(" · ") || null;
}

function agentsCaption(run: RunState, liveMs: number): string | null {
  const live = waitingCaption(run.agentEvents, run.stageFacts.agents, liveMs);
  const agentic = run.payload?.decision.agentic;
  // ultrareview: этап может быть "skipped" (агенты не привлекались вовсе — отказ на данных, или
  // fallback без единого мнения), и раньше это молча падало обратно в live-заглушку "ещё не
  // обращался к специалистам" — неверно для уже завершённого прогона.
  if (run.stages.agents === "skipped") {
    if (run.payload?.agentic_state) return "не привлекались · агенты выключены";
    if (!agentic) return live;
    return agentic.fallback_reason ? `не привлекались · ${agentic.fallback_reason}` : "не привлекались";
  }
  if (run.stages.agents !== "done") return live;
  if (!agentic) return live;
  const overridden = agentic.llm_choice_overridden === true ? "выбор переопределён" : null;
  const calls = run.agentEvents.length > 0 ? `событий ${run.agentEvents.length}` : null;
  return [agentic.outcome ? `итог ${agentic.outcome}` : null, overridden, calls]
    .filter(Boolean).join(" · ") || live;
}

export function nodeCaption(
  id: string,
  started: boolean,
  waiting: string,
  run: RunState,
  liveMs: number
): string {
  if (!started) return waiting;
  if (id === "agents") {
    return agentsCaption(run, liveMs) ?? waiting;
  }
  if (id === "decision") {
    return decisionCaption(run.payload) ?? waiting;
  }
  return stateCaption(id, run.stageFacts[id]) ?? waiting;
}

export function candidatesLoopLabel(facts: StageFacts | undefined): string | null {
  const rounds = facts?.rounds;
  if (typeof rounds !== "number" || rounds <= 1) return null;
  return `раунд ${rounds} из 3`;
}

export function replansCount(payload: ScreenPayload | null): number {
  const replans = payload?.decision.agentic?.budget?.replans;
  return typeof replans === "number" ? replans : 0;
}

export function backEdgeActive(payload: ScreenPayload | null): boolean {
  return replansCount(payload) > 0;
}
