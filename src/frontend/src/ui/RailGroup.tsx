import type { ReactNode } from "react";
import type { SummaryLine } from "../run/summary";

export interface RailGroupProps {
  title: string;
  children: ReactNode;
}

export function RailGroup({ title, children }: RailGroupProps) {
  return (
    <section className="rail__group">
      <h2 className="rail__title">
        <span className="rail__tick" aria-hidden="true" />
        {title}
      </h2>
      {children}
    </section>
  );
}

export function RailLines({ lines }: { lines: SummaryLine[] }) {
  return (
    <dl className="rail__lines">
      {lines.map((line) => (
        <div key={line.label} className={`rail__line rail__line--${line.tone}`}>
          <dt>{line.label}</dt>
          <dd>{line.value}</dd>
        </div>
      ))}
    </dl>
  );
}
