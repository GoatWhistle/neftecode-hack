import type { MapNode } from "./graph";

export interface InputNodeProps {
  node: MapNode;
  caption: string;
}

export function InputNode({ node, caption }: InputNodeProps) {
  return (
    <div className="mapnode mapnode--input" data-map-node={node.id}>
      <span className="mapnode__kind">вход</span>
      <span className="mapnode__title">{node.label}</span>
      <span className="mapnode__artifact">{caption}</span>
    </div>
  );
}
