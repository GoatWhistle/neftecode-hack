import type { MapNode } from "./graph";

export type TerminalState = "idle" | "taken" | "refused";

export interface TerminalNodeProps {
  node: MapNode;
  state: TerminalState;
  onSelect?: (() => void) | undefined;
}

const WORD: Record<TerminalState, string> = {
  idle: "не выбран",
  taken: "исход прогона",
  refused: "исход прогона"
};

export function TerminalNode({ node, state, onSelect }: TerminalNodeProps) {
  const className = `mapnode mapnode--terminal mapnode--term-${state}`;
  const body = (
    <>
      <span className="mapnode__kind">исход</span>
      <span className="mapnode__title mapnode__title--mono">{node.label}</span>
      <span className="mapnode__artifact">{state === "idle" ? node.artifact : WORD[state]}</span>
    </>
  );

  if (onSelect) {
    return (
      <button
        type="button"
        className={`${className} mapnode--link`}
        data-map-node={node.id}
        aria-label={`Исход ${node.label}, ${WORD[state]}, перейти к итогу`}
        onClick={onSelect}
      >
        {body}
      </button>
    );
  }

  return (
    <div className={className} data-map-node={node.id} aria-label={`Исход ${node.label}, ${WORD[state]}`}>
      {body}
    </div>
  );
}
