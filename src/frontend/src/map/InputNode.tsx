import type { MapNode } from "./graph";
import { InputMark } from "./InputMark";

export interface InputNodeProps {
  node: MapNode;
  caption: string;
  locked?: boolean;
  expanded?: boolean;
  panelId?: string;
  onSelect?: (id: string) => void;
}

export function InputNode({ node, caption, locked, expanded, panelId, onSelect }: InputNodeProps) {
  const word = locked ? "задано" : "нужно задать";
  if (!onSelect || !panelId) {
    return (
      <div className="mapnode mapnode--input" data-map-node={node.id}>
        <span className="mapnode__top">
          <span className="mapnode__title">{node.label}</span>
          <InputMark locked={locked === true} />
        </span>
        <span className="mapnode__artifact">{caption}</span>
        <span className="mapnode__foot" />
      </div>
    );
  }
  const open = expanded === true;
  return (
    <button
      type="button"
      className={`mapnode mapnode--stage mapnode--input ${open ? "mapnode--open" : ""} ${
        locked ? "mapnode--input-locked" : "mapnode--input-free"
      } ${open ? "mapnode--input-open" : ""}`}
      data-map-node={node.id}
      aria-expanded={open}
      aria-controls={open ? panelId : undefined}
      aria-label={`Этап 0, ${node.label}, ${word}, ${open ? "свернуть" : "раскрыть"}`}
      onClick={() => onSelect(node.id)}
    >
      <span className="mapnode__top">
        <span className="mapnode__title">{node.label}</span>
        <InputMark locked={locked === true} />
      </span>
      <span className="mapnode__artifact">{caption}</span>
      <span className="mapnode__foot" />
    </button>
  );
}
