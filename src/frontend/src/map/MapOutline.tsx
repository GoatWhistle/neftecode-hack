import { spanText } from "../format";
import { STATE_WORD } from "../run/railStatus";
import type { RunState, StageState } from "../run/types";
import { MAP_NODES } from "./graph";
import { spentOf } from "./mapRuntime";

export interface MapOutlineProps {
  run: RunState;
  liveMs: number;
  stateOf: (id: string) => StageState;
}

export function MapOutline({ run, liveMs, stateOf }: MapOutlineProps) {
  return (
    <ol className="sr-only">
      {MAP_NODES.filter((node) => node.kind === "stage").map((node) => {
        const state = stateOf(node.id);
        const spent = spentOf(run, node.id, state, liveMs);
        return (
          <li key={node.id}>
            {`этап ${node.order} из 8, ${node.label}, ${STATE_WORD[state]}`}
            {spent === null ? "" : `, ${spanText(spent)}`}
          </li>
        );
      })}
    </ol>
  );
}
