import type { AgentEvent } from "../run/types";
import type { Agentic } from "../types";
import { AGENT_NAMES } from "../run/agentEvents";

export type NodeKind = "orchestrator" | "specialist" | "outcome";

export type EdgeKind = "ask" | "answer" | "tool" | "finalize";

export type EdgeTone = "neutral" | "pass" | "warn" | "fail";

export interface GraphNode {
  id: string;
  title: string;
  kind: NodeKind;
  role: string;
  x: number;
  y: number;
  bornAt: number;
  calls: number;
  tools: string[];
  verdict: string | null;
  risk: string | null;
  confidence: number | null;
  events: AgentEvent[];
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  tone: EdgeTone;
  label: string;
  detail: string | null;
  order: number;
  seq: number;
  atMs: number;
  spentMs: number | null;
  events: AgentEvent[];
}

export interface GraphModel {
  nodes: GraphNode[];
  edges: GraphEdge[];
  steps: number;
  width: number;
  height: number;
  absent: string | null;
}

const VERDICT_TONE: Record<string, EdgeTone> = {
  ACCEPT: "pass",
  REVISE: "warn",
  REJECT: "fail",
  UNKNOWN: "neutral"
};

const VERDICT_WORD: Record<string, string> = {
  ACCEPT: "принял",
  REVISE: "просил доработать",
  REJECT: "отклонил",
  UNKNOWN: "данных не хватило"
};

const TOOL_WORD: Record<string, string> = {
  get_quality_margins: "запас качества",
  get_setpoint_changes: "перестановки уставок",
  get_forecast_and_uncertainty: "прогноз и разброс",
  get_tank_projection: "проекция резервуара",
  search_candidates: "поиск планов",
  rank_allowed: "ранжирование",
  inspect_candidate: "разбор плана",
  compare_candidates: "сравнение планов"
};

const CANVAS_W = 880;
const CANVAS_H = 470;
const HUB_X = 140;
const HUB_Y = 178;
const LANE_X = 452;

function specialistSpot(index: number, total: number): { x: number; y: number } {
  if (total === 1) return { x: LANE_X, y: HUB_Y };
  const gap = Math.min(230, 460 / Math.max(1, total - 1));
  const top = HUB_Y - (gap * (total - 1)) / 2;
  return { x: LANE_X, y: top + gap * index };
}

function spentOf(event: AgentEvent, all: AgentEvent[]): number | null {
  const index = all.indexOf(event);
  if (index <= 0) return null;
  const before = all[index - 1];
  if (before === undefined) return null;
  const gap = event.elapsedMs - before.elapsedMs;
  return gap >= 0 ? gap : null;
}

function askedFocus(event: AgentEvent): string | null {
  const raw = event.tool_input_summary;
  if (!raw) return null;
  const match = raw.match(/"focus"\s*:\s*"([^"]{1,90})/);
  return match === null ? null : (match[1] ?? null);
}

export function buildGraph(events: AgentEvent[], agentic: Agentic | null): GraphModel {
  if (events.length === 0) {
    return { nodes: [], edges: [], steps: 0, width: CANVAS_W, height: CANVAS_H,
      absent: "События агентов по этому прогону не передавались." };
  }

  const roles: string[] = [];
  for (const event of events) {
    const role = event.agent;
    if (role === "orchestrator" || role === "system") continue;
    if (!roles.includes(role)) roles.push(role);
  }

  const opinions = agentic?.opinions ?? [];
  const opinionOf = (role: string) => opinions.find((one) => one.role === role) ?? null;

  const nodes: GraphNode[] = [];
  const hubEvents = events.filter((event) => event.agent === "orchestrator");
  nodes.push({
    id: "orchestrator",
    title: AGENT_NAMES["orchestrator"] ?? "оркестратор",
    kind: "orchestrator",
    role: "ведёт цикл и сводит мнения",
    x: HUB_X,
    y: HUB_Y,
    bornAt: 0,
    calls: hubEvents.filter((event) => event.kind === "llm_call").length,
    tools: [...new Set(hubEvents.filter((e) => e.kind === "tool").map((e) => e.tool_name ?? ""))]
      .filter((name) => name !== ""),
    verdict: null,
    risk: null,
    confidence: null,
    events: hubEvents
  });

  roles.forEach((role, index) => {
    const spot = specialistSpot(index, roles.length);
    const own = events.filter((event) => event.agent === role);
    const opinion = opinionOf(role);
    const first = own[0];
    const born = first === undefined ? 0 : first.seq;
    nodes.push({
      id: role,
      title: AGENT_NAMES[role] ?? role,
      kind: "specialist",
      role: role === "quality" ? "вето по свойствам продукта" : "вето по режиму и оборудованию",
      x: spot.x,
      y: spot.y,
      bornAt: born,
      calls: own.filter((event) => event.kind === "llm_call").length,
      tools: [...new Set(own.filter((e) => e.kind === "tool").map((e) => e.tool_name ?? ""))]
        .filter((name) => name !== ""),
      verdict: opinion?.verdict ?? null,
      risk: opinion?.risk_level ?? null,
      confidence: typeof opinion?.confidence === "number" ? opinion.confidence : null,
      events: own
    });
  });

  const last = events[events.length - 1];
  const lastSeq = last === undefined ? 0 : last.seq;
  const chosen = agentic?.final?.candidate_id ?? null;
  nodes.push({
    id: "outcome",
    title: chosen === null ? "итог" : `план ${chosen}`,
    kind: "outcome",
    role: agentic?.final?.summary ?? "итог цикла",
    x: HUB_X,
    y: CANVAS_H - 62,
    bornAt: lastSeq,
    calls: 0,
    tools: [],
    verdict: null,
    risk: null,
    confidence: null,
    events: events.filter((event) => event.kind === "final" && event.agent === "orchestrator")
  });

  const edges: GraphEdge[] = [];
  let order = 0;

  for (const event of events) {
    if (event.kind === "consult") {
      const role = (event.tool_name ?? "").replace("ask_", "").replace("_agent", "");
      if (!roles.includes(role)) continue;
      const focus = askedFocus(event);
      edges.push({
        id: `ask-${event.seq}`,
        from: "orchestrator",
        to: role,
        kind: "ask",
        tone: "neutral",
        label: "спросил",
        detail: focus,
        order: order++,
        seq: event.seq,
        atMs: event.elapsedMs,
        spentMs: spentOf(event, events),
        events: [event]
      });
      continue;
    }

    if (event.kind === "tool" && event.agent !== "orchestrator") {
      const name = event.tool_name ?? "";
      edges.push({
        id: `tool-${event.seq}`,
        from: event.agent,
        to: event.agent,
        kind: "tool",
        tone: event.decision === "error" ? "fail" : "neutral",
        label: TOOL_WORD[name] ?? name,
        detail: event.tool_result_summary ?? null,
        order: order++,
        seq: event.seq,
        atMs: event.elapsedMs,
        spentMs: spentOf(event, events),
        events: [event]
      });
      continue;
    }

    if (event.kind === "resolution") {
      const parts = (event.decision ?? "").split(":");
      const role = parts[0] ?? "";
      const verdict = parts[1] ?? "";
      if (!roles.includes(role)) continue;
      edges.push({
        id: `answer-${event.seq}`,
        from: role,
        to: "orchestrator",
        kind: "answer",
        tone: VERDICT_TONE[verdict] ?? "neutral",
        label: VERDICT_WORD[verdict] ?? verdict,
        detail: event.tool_result_summary ?? null,
        order: order++,
        seq: event.seq,
        atMs: event.elapsedMs,
        spentMs: spentOf(event, events),
        events: [event]
      });
      continue;
    }

    if (event.kind === "final" && event.agent === "orchestrator") {
      edges.push({
        id: `final-${event.seq}`,
        from: "orchestrator",
        to: "outcome",
        kind: "finalize",
        tone: event.decision === "accepted" ? "pass" : "warn",
        label: chosen === null ? "свёл итог" : `выбрал ${chosen}`,
        detail: agentic?.final?.summary ?? null,
        order: order++,
        seq: event.seq,
        atMs: event.elapsedMs,
        spentMs: spentOf(event, events),
        events: [event]
      });
    }
  }

  return { nodes, edges, steps: order, width: CANVAS_W, height: CANVAS_H, absent: null };
}
