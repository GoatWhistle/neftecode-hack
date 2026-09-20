import { duration } from "../format";
import type { RunState, StageState } from "../run/types";
import { STATE_WORD } from "../run/railStatus";
import type { MapNode } from "./graph";
import { nodeCaption } from "./nodeFacts";

export interface StageNodeProps {
  node: MapNode;
  state: StageState;
  spentMs: number | null;
  run: RunState;
  liveMs: number;
  started: boolean;
  expanded: boolean;
  panelId?: string | undefined;
  onSelect: (id: string) => void;
}

function timeText(state: StageState, spentMs: number | null): string | null {
  if (spentMs === null) return null;
  if (state !== "running" && spentMs < 100) return "<0,1";
  return duration(spentMs);
}

export function StageNode({ node, state, spentMs, run, liveMs, started, expanded, panelId, onSelect }: StageNodeProps) {
  const order = node.order ?? 0;
  const time = timeText(state, spentMs);
  const word = STATE_WORD[state];
  const hint = panelId ? (expanded ? "свернуть" : "раскрыть") : "перейти к итогу";
  const caption = nodeCaption(node.id, started, node.waiting, run, liveMs);
  return (
    <button
      type="button"
      className={`mapnode mapnode--stage mapnode--${state} ${expanded ? "mapnode--open" : ""}`}
      data-map-node={node.id}
      aria-expanded={panelId ? expanded : undefined}
      aria-controls={panelId && expanded ? panelId : undefined}
      aria-label={`Этап ${order}, ${node.label}, ${word}, ${hint}`}
      onClick={() => onSelect(node.id)}
    >
      <span className="mapnode__top">
        <span className="mapnode__order">{String(order).padStart(2, "0")}</span>
        <span className="mapnode__word">{word}</span>
      </span>
      <span className="mapnode__title">{node.label}</span>
      <span className="mapnode__artifact">{caption}</span>
      <span className="mapnode__foot">{time === null ? "" : time}</span>
    </button>
  );
}
