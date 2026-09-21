import type { TransitionEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { scrollToDrawer } from "../run/autoscroll";
import { focusNode, instant } from "./mapRuntime";

export interface DrawerSlot {
  shown: string | null;
  onSlotTransitionEnd: (event: TransitionEvent<HTMLDivElement>) => void;
}

export function useDrawerSlot(
  open: string | null,
  board: HTMLElement | null,
  panelId: string,
  printing: boolean
): DrawerSlot {
  const [shown, setShown] = useState<string | null>(open);
  const lastOpen = useRef<string | null>(null);

  useEffect(() => {
    if (open !== null) setShown(open);
    if (open === null && lastOpen.current !== null && board) {
      focusNode(board, lastOpen.current);
    }
    lastOpen.current = open;
  }, [open, board]);

  useEffect(() => {
    if (open !== null || shown === null || !instant()) return;
    setShown(null);
  }, [open, shown]);

  const onSlotTransitionEnd = useCallback(
    (event: TransitionEvent<HTMLDivElement>) => {
      if (event.propertyName !== "grid-template-rows") return;
      window.dispatchEvent(new Event("resize"));
      if (event.currentTarget.dataset["open"] === "true") {
        if (!printing) scrollToDrawer(panelId);
        return;
      }
      setShown((current) => (current === null ? current : null));
    },
    [panelId, printing]
  );

  return { shown, onSlotTransitionEnd };
}
