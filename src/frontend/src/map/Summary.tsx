import type { ScreenPayload } from "../types";
import type { StageState } from "../run/types";
import { lampOf } from "../stages";
import { DecisionStage } from "../stages/DecisionStage";

export const SUMMARY_ID = "summary";

export interface SummaryProps {
  payload: ScreenPayload;
  state: StageState;
}

export function Summary({ payload, state }: SummaryProps) {
  const signal = lampOf("decision", payload);
  return (
    <section className="summary stage--final" id={SUMMARY_ID} aria-labelledby="summary-title">
      <header className="summary__head">
        <span className="summary__step">8</span>
        <h2 className="summary__title" id="summary-title">
          Итог
        </h2>
        <p className="summary__lead">{payload.status_label}</p>
      </header>
      <DecisionStage
        payload={payload}
        index={8}
        state={state}
        lamp={signal.lamp}
        lampTitle={signal.title}
        bare
      />
    </section>
  );
}
