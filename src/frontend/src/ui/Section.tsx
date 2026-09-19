import type { ReactNode } from "react";
import type { StageState } from "../run/types";
import type { Lamp } from "./Primitives";
import { LampDot } from "./Primitives";
import { STATE_WORD } from "../run/railStatus";

export interface SectionProps {
  id: string;
  index: number;
  title: string;
  lead: string;
  lamp: Lamp;
  lampTitle?: string | undefined;
  state?: StageState | undefined;
  source?: string | undefined;
  final?: boolean;
  children: ReactNode;
}

export function Section({
  id,
  index,
  title,
  lead,
  lamp,
  lampTitle,
  state = "done",
  source,
  final = false,
  children
}: SectionProps) {
  return (
    <section
      id={id}
      className={`stage stage--${state} ${final ? "stage--final" : ""}`}
      data-stage-state={state}
      data-band={index}
    >
      <header className="stage__head">
        <span className="stage__step">{index}</span>
        <h2 className="stage__title">
          <LampDot state={lamp} title={lampTitle} />
          {title}
          <span className="sr-only">, </span>
          <span className="stage__state">{STATE_WORD[state]}</span>
        </h2>
        <p className="stage__lead">{lead}</p>
        {source ? <p className="stage__source">{source}</p> : null}
      </header>
      <div className="stage__body">{children}</div>
    </section>
  );
}
