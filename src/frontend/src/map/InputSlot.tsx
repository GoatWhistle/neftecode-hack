import type { ReactNode } from "react";
import type { RunState } from "../run/types";
import { Drawer } from "./Drawer";
import { INPUT_SCENARIO } from "./graph";

export const INPUT_PANEL_ID = "map-drawer-input";

export interface InputSlotProps {
  run: RunState;
  body: ReactNode;
  meta: string;
}

export function InputSlot({ run, body, meta }: InputSlotProps) {
  return (
    <div className="map__slot map__slot--up" data-open="true">
      <Drawer
        id={INPUT_SCENARIO}
        panelId={INPUT_PANEL_ID}
        run={run}
        state="pending"
        focusOnMount={false}
        body={body}
        meta={meta}
        pinned
      />
    </div>
  );
}
