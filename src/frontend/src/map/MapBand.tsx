import type { ReactNode, TransitionEvent } from "react";
import type { RunState, StageState } from "../run/types";
import { Drawer } from "./Drawer";
import type { MapNode } from "./graph";
import { INPUT_SCENARIO, nodeById } from "./graph";
import { InputSlot } from "./InputSlot";
import type { MapRow } from "./layout";

export const PANEL_ID = "map-drawer";

export interface MapBandProps {
  row: MapRow;
  run: RunState;
  printing: boolean;
  stageOpen: string | null;
  shown: string | null;
  inputOpen: string | null;
  shownInput: string | null;
  inputPanel: ReactNode;
  inputMeta: string;
  stateOf: (id: string) => StageState;
  renderNode: (node: MapNode) => ReactNode;
  onClose: () => void;
  onSlotTransitionEnd: (event: TransitionEvent<HTMLDivElement>) => void;
  onInputTransitionEnd: (event: TransitionEvent<HTMLDivElement>) => void;
}

export function MapBand({
  row,
  run,
  printing,
  stageOpen,
  shown,
  inputOpen,
  shownInput,
  inputPanel,
  inputMeta,
  stateOf,
  renderNode,
  onClose,
  onSlotTransitionEnd,
  onInputTransitionEnd
}: MapBandProps) {
  const stageCells = row.cells.filter((id) => id !== INPUT_SCENARIO);
  const rowOpen = stageCells.find((id) => (printing ? id !== "decision" : id === stageOpen));
  const rowShown = stageCells.find((id) => (printing ? id !== "decision" : id === shown));
  const hasInput = row.cells.includes(INPUT_SCENARIO);
  const upOpen = hasInput && (printing || inputOpen !== null);
  const upShown = hasInput && (printing || shownInput !== null);

  return (
    <div className="map__band">
      {hasInput && inputPanel ? (
        <InputSlot
          run={run}
          body={inputPanel}
          meta={inputMeta}
          open={upOpen}
          shown={upShown}
          printing={printing}
          onClose={onClose}
          onTransitionEnd={onInputTransitionEnd}
        />
      ) : null}
      <div className={`map__row map__row--${row.direction}`}>
        <div className="map__cells">
          {row.cells.map((id) => {
            const node = nodeById(id);
            return node ? renderNode(node) : null;
          })}
          {row.terminals ? (
            <div className="map__terminals">
              {row.terminals.map((id) => {
                const node = nodeById(id);
                return node ? renderNode(node) : null;
              })}
            </div>
          ) : null}
        </div>
      </div>
      <div
        className="map__slot"
        data-open={rowOpen !== undefined}
        onTransitionEnd={onSlotTransitionEnd}
      >
        {rowShown !== undefined ? (
          <Drawer
            id={rowShown}
            panelId={PANEL_ID}
            run={run}
            state={stateOf(rowShown)}
            onClose={onClose}
            focusOnMount={!printing}
            inert={rowOpen === undefined}
          />
        ) : null}
      </div>
    </div>
  );
}
