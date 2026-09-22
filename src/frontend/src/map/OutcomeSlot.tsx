import type { ReactNode } from "react";

export const OUTCOME_PANEL_ID = "map-drawer-outcome";
export const OUTCOME_NODE_ID = "out-summary";

export interface OutcomeSlotProps {
  body: ReactNode;
  meta: string;
  title: string;
}

export function OutcomeSlot({ body, meta, title }: OutcomeSlotProps) {
  return (
    <div className="map__slot map__slot--down" data-open="true" data-map-node={OUTCOME_NODE_ID}>
      <div className="drawer drawer--pinned drawer--outcome" id={OUTCOME_PANEL_ID} role="region"
        aria-label={`Итог прогона: ${title}`}>
        <div className="drawer__inner">
          <header className="drawer__head">
            <h2 className="drawer__title">
              <span className="drawer__name">{title}</span>
            </h2>
            <p className="drawer__meta">{meta}</p>
          </header>
          {body}
        </div>
      </div>
    </div>
  );
}
