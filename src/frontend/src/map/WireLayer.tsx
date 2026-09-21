import { useEffect, useRef, useState } from "react";
import type { EdgeKind } from "./graph";
import type { Wire } from "./wires";

export type WireState = "idle" | "drawn" | "alert";

export interface WireLayerProps {
  wires: Wire[];
  width: number;
  height: number;
  stateOf: (wire: Wire) => WireState;
}

const HEAD_SPAN: Record<EdgeKind, number> = {
  flow: 6,
  loop: 4.5,
  back: 4.5,
  exit: 4.5
};

function classOf(wire: Wire, state: WireState): string {
  return `wire wire--${wire.kind} wire--${state}`;
}

function arrow(x: number, y: number, span: number): string {
  const half = span * 0.52;
  return `M ${x} ${y} L ${x - span} ${y - half} L ${x - span} ${y + half} Z`;
}

export function WireLayer({ wires, width, height, stateOf }: WireLayerProps) {
  const [drawn, setDrawn] = useState<Record<string, boolean>>({});
  const seen = useRef<Record<string, WireState>>({});

  useEffect(() => {
    let changed = false;
    const next = { ...seen.current };
    for (const wire of wires) {
      const state = stateOf(wire);
      if (next[wire.id] !== state) {
        next[wire.id] = state;
        changed = true;
      }
    }
    if (!changed) return;
    seen.current = next;
    setDrawn(() => {
      const map: Record<string, boolean> = {};
      for (const wire of wires) {
        map[wire.id] = next[wire.id] !== "idle";
      }
      return map;
    });
  }, [wires, stateOf]);

  if (width <= 0 || height <= 0) return null;

  return (
    <svg
      className="wires"
      width={width}
      height={height}
      viewBox={`0 0 ${Math.round(width)} ${Math.round(height)}`}
      aria-hidden="true"
      focusable="false"
    >
      {wires.map((wire) => {
        const state = stateOf(wire);
        const live = drawn[wire.id] === true;
        return (
          <g key={wire.id} className={classOf(wire, state)}>
            <path className="wire__track" d={wire.path} />
            {wire.kind === "flow" ? (
              <path
                className="wire__line"
                d={wire.path}
                style={{ strokeDasharray: wire.length, strokeDashoffset: live ? 0 : wire.length }}
              />
            ) : null}
            <path
              className="wire__head"
              d={arrow(
                wire.head.x,
                wire.head.y,
                state === "alert" ? HEAD_SPAN.flow : HEAD_SPAN[wire.kind]
              )}
              transform={`rotate(${wire.head.angle} ${wire.head.x} ${wire.head.y})`}
            />
            {wire.label && wire.labelAt ? (
              <text
                className="wire__label"
                x={wire.labelAt.x}
                y={wire.labelAt.y + (wire.labelDy ?? -6)}
                textAnchor={wire.labelAnchor ?? "middle"}
              >
                {wire.labelLines ? (
                  wire.labelLines.map((line, index) => (
                    <tspan key={line} x={wire.labelAt?.x} dy={index === 0 ? 0 : "1.15em"}>
                      {line}
                    </tspan>
                  ))
                ) : (
                  wire.label
                )}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}
