import type { ReactNode } from "react";
import type { StageState } from "../run/types";
import type { Lamp } from "./Primitives";

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
  bare?: boolean | undefined;
  children: ReactNode;
}

export function Section({ id, children }: SectionProps) {
  return (
    <div className="stage__body stage__body--bare" data-stage-body={id}>
      {children}
    </div>
  );
}
