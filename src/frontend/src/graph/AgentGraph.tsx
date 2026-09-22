import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphModel, GraphNode } from "./model";

const STEP_MS = 420;
const CATCHUP_MS = 130;
const LIVE_MS = 300;
const LIVE_FLOOR_MS = 150;
const LIVE_BUDGET_MS = 2600;

function nodeRadius(node: GraphNode): number {
  if (node.kind === "orchestrator") return 44;
  if (node.kind === "outcome") return 27;
  return 37;
}

interface Geometry {
  path: string;
  labelX: number;
  labelY: number;
  anchor: "start" | "middle" | "end";
}

interface ToolUse {
  label: string;
  times: number;
  failed: boolean;
}

const TOOL_ROW = 21;
const TOOL_GAP = 74;

function geometryOf(from: GraphNode, to: GraphNode, lift: number): Geometry {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.max(1, Math.hypot(dx, dy));
  const ux = dx / len;
  const uy = dy / len;
  const nx = -uy;
  const ny = ux;
  const pad = 8;
  const sx = from.x + ux * (nodeRadius(from) + pad);
  const sy = from.y + uy * (nodeRadius(from) + pad);
  const ex = to.x - ux * (nodeRadius(to) + pad);
  const ey = to.y - uy * (nodeRadius(to) + pad);
  const cx = (sx + ex) / 2 + nx * lift;
  const cy = (sy + ey) / 2 + ny * lift;
  const apexX = (sx + ex) / 4 + cx / 2;
  const apexY = (sy + ey) / 4 + cy / 2;
  const away = lift < 0 ? -1 : 1;
  return {
    path: `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`,
    labelX: apexX + nx * away * 17,
    labelY: apexY + ny * away * 17 + (ny * away < -0.4 ? -5 : 7),
    anchor: "middle"
  };
}

function edgeLift(edge: GraphEdge): number {
  if (edge.kind === "ask") return -38;
  if (edge.kind === "answer") return -38;
  return 0;
}

function spanOf(edge: GraphEdge): string | null {
  const spent = edge.spentMs;
  if (spent === null || spent < 5) return null;
  if (spent < 950) return `${Math.round(spent / 10) * 10} мс`;
  return `${(spent / 1000).toFixed(1).replace(".", ",")} с`;
}

function padSeq(seq: number): string {
  return seq < 10 ? `0${seq}` : String(seq);
}

export interface AgentGraphProps {
  model: GraphModel;
  selected: string | null;
  onSelect: (id: string | null) => void;
  reveal: number;
  live: boolean;
}

export function AgentGraph({ model, selected, onSelect, reveal, live }: AgentGraphProps) {
  const byId = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of model.nodes) map.set(node.id, node);
    return map;
  }, [model]);

  const head = model.edges[reveal - 1] ?? null;
  const hot = live ? head : null;

  const toolsOf = useMemo(() => {
    const out = new Map<string, ToolUse[]>();
    for (const edge of model.edges) {
      if (edge.kind !== "tool") continue;
      if (edge.order >= reveal) continue;
      const list = out.get(edge.from) ?? [];
      const seen = list.find((one) => one.label === edge.label);
      if (seen === undefined) {
        list.push({ label: edge.label, times: 1, failed: edge.tone === "fail" });
      } else {
        seen.times += 1;
        if (edge.tone === "fail") seen.failed = true;
      }
      out.set(edge.from, list);
    }
    return out;
  }, [model, reveal]);

  const lanes = useMemo(
    () => model.nodes.filter((node) => node.kind === "specialist"),
    [model]
  );

  return (
    <svg className="agraph__svg" viewBox={`0 0 ${model.width} ${model.height}`}
      role="img" aria-label="Карта обмена между агентами">
      <defs>
        <marker id="agraph-head" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" className="agraph__head" />
        </marker>
        <marker id="agraph-head-pass" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" className="agraph__head agraph__head--pass" />
        </marker>
        <marker id="agraph-head-warn" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" className="agraph__head agraph__head--warn" />
        </marker>
        <marker id="agraph-head-fail" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" className="agraph__head agraph__head--fail" />
        </marker>
        <pattern id="agraph-grid" width="26" height="26" patternUnits="userSpaceOnUse">
          <path d="M 26 0 L 0 0 0 26" className="agraph__grid" />
        </pattern>
      </defs>

      <rect className="agraph__field" x="0" y="0" width={model.width} height={model.height}
        fill="url(#agraph-grid)" />

      <g className="agraph__lanes" aria-hidden="true">
        {lanes.map((node) => (
          <line key={node.id} className="agraph__lane"
            x1={128} y1={node.y} x2={node.x - nodeRadius(node) - 14} y2={node.y} />
        ))}
      </g>

      <g className="agraph__edges">
        {model.edges.map((edge) => {
          if (edge.kind === "tool") return null;
          const from = byId.get(edge.from);
          const to = byId.get(edge.to);
          if (from === undefined || to === undefined) return null;
          const shown = edge.order < reveal;
          const dim = selected !== null && selected !== edge.from && selected !== edge.to;
          const isHot = hot !== null && hot.id === edge.id;
          const geo = geometryOf(from, to, edgeLift(edge));
          const span = spanOf(edge);
          const marker = edge.tone === "pass" ? "url(#agraph-head-pass)"
            : edge.tone === "warn" ? "url(#agraph-head-warn)"
              : edge.tone === "fail" ? "url(#agraph-head-fail)"
                : "url(#agraph-head)";
          return (
            <g key={edge.id}
              className={`agraph__edge agraph__edge--${edge.kind} agraph__edge--${edge.tone}${
                shown ? " is-shown" : ""}${dim ? " is-dim" : ""}${isHot ? " is-hot" : ""}`}>
              <path className="agraph__halo" d={geo.path} pathLength={1} />
              <path className="agraph__wire" d={geo.path}
                markerEnd={marker} pathLength={1} />
              {isHot ? (
                <circle className="agraph__spark" r="3.4">
                  <animateMotion dur="1.05s" repeatCount="indefinite" path={geo.path} />
                </circle>
              ) : null}
              <text className="agraph__tag" x={geo.labelX} y={geo.labelY} textAnchor={geo.anchor}>
                <tspan className="agraph__ord">{padSeq(edge.seq)} </tspan>
                {edge.label}
                {span === null ? null : <tspan className="agraph__when"> · {span}</tspan>}
              </text>
            </g>
          );
        })}
      </g>

      <g className="agraph__nodes">
        {model.nodes.map((node) => {
          const shown = node.kind === "orchestrator"
            || model.edges.some((edge) =>
              edge.order < reveal && (edge.from === node.id || edge.to === node.id));
          const active = selected === node.id;
          const busy = hot !== null && (hot.from === node.id || hot.to === node.id);
          const radius = nodeRadius(node);
          return (
            <g key={node.id}
              className={`agraph__node agraph__node--${node.kind}${shown ? " is-shown" : ""}${
                active ? " is-active" : ""}${busy ? " is-busy" : ""}`}
              transform={`translate(${node.x} ${node.y})`}
              tabIndex={shown ? 0 : -1}
              role="button"
              aria-pressed={active}
              aria-label={`${node.title}: ${node.role}`}
              onClick={() => onSelect(active ? null : node.id)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                onSelect(active ? null : node.id);
              }}>
              <circle r={radius + 11} className="agraph__pulse" />
              <circle r={radius} cx={2} cy={3} className="agraph__shade" />
              <circle r={radius} className="agraph__disc" />
              {node.verdict !== null ? (
                <circle r={radius + 6} className={`agraph__ring agraph__ring--${node.verdict}`} />
              ) : null}
              {node.kind === "outcome" ? (
                <path className="agraph__tick" d="M -7 0 L -2 5 L 8 -6" />
              ) : (
                <>
                  <text className="agraph__count" y={-2}>{node.calls}</text>
                  <text className="agraph__unit" y={18}>вызовов</text>
                </>
              )}
              <text className="agraph__name" y={radius + 26}>{node.title}</text>
              {node.kind === "specialist" && node.verdict !== null ? (
                <text className={`agraph__verdict agraph__verdict--${node.verdict}`}
                  y={-radius - 13}>
                  {node.verdict}
                </text>
              ) : null}
              {(() => {
                const used = toolsOf.get(node.id) ?? [];
                if (used.length === 0) return null;
                const x = radius + TOOL_GAP;
                const stem = radius + 16;
                const span = (used.length - 1) * TOOL_ROW;
                const top = -span / 2;
                return (
                  <g className="agraph__tools" aria-hidden="true">
                    {used.map((tool, row) => {
                      const y = top + row * TOOL_ROW;
                      const bend = stem + 14;
                      return (
                        <g key={tool.label} className={`agraph__tool-row${
                          tool.failed ? " agraph__tool-row--fail" : ""}`}>
                          <path className="agraph__tool-wire"
                            d={`M ${radius + 3} 0 L ${stem} 0 C ${bend} 0 ${bend} ${y} ${x - 7} ${y}`} />
                          <text className="agraph__tool" x={x} y={y + 4}>
                            {tool.label}
                            {tool.times > 1 ? (
                              <tspan className="agraph__tool-times"> ×{tool.times}</tspan>
                            ) : null}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                );
              })()}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export function useLiveReveal(total: number, settled: boolean): number {
  const [shown, setShown] = useState(0);
  const timer = useRef<number | null>(null);
  const shownRef = useRef(0);

  shownRef.current = shown;

  useEffect(() => {
    const clear = () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      timer.current = null;
    };

    if (total === 0) {
      clear();
      setShown(0);
      return clear;
    }

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      clear();
      setShown(total);
      return clear;
    }

    if (shownRef.current > total) {
      clear();
      setShown(total);
      return clear;
    }

    if (shownRef.current >= total) {
      clear();
      return clear;
    }

    const behind = total - shownRef.current;
    const pace = settled
      ? (behind > 3 ? CATCHUP_MS : STEP_MS)
      : Math.max(LIVE_FLOOR_MS, Math.min(LIVE_MS, LIVE_BUDGET_MS / behind));
    clear();
    timer.current = window.setInterval(() => {
      setShown((was) => {
        const next = was + 1;
        if (next >= total) clear();
        return next > total ? total : next;
      });
    }, pace);

    return clear;
  }, [total, settled]);

  return shown;
}
