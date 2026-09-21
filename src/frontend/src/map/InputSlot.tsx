import type { ReactNode } from "react";
import type { TransitionEvent } from "react";
import type { RunState } from "../run/types";
import { Drawer } from "./Drawer";
import { INPUT_SCENARIO } from "./graph";

export const INPUT_PANEL_ID = "map-drawer-input";

export interface InputSlotProps {
  run: RunState;
  body: ReactNode;
  meta: string;
  open: boolean;
  shown: boolean;
  printing: boolean;
  onClose: () => void;
  onTransitionEnd: (event: TransitionEvent<HTMLDivElement>) => void;
}

export function InputSlot({
  run,
  body,
  meta,
  open,
  shown,
  printing,
  onClose,
  onTransitionEnd
}: InputSlotProps) {
  return (
    <div className="map__slot map__slot--up" data-open={open} onTransitionEnd={onTransitionEnd}>
      {shown ? (
        <Drawer
          id={INPUT_SCENARIO}
          panelId={INPUT_PANEL_ID}
          run={run}
          state="pending"
          onClose={onClose}
          focusOnMount={!printing}
          inert={!open}
          body={body}
          meta={meta}
          closeLabel="Закрыть условия прогона"
        />
      ) : null}
    </div>
  );
}
