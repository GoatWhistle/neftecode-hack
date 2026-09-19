import type { ReactNode } from "react";
import { MISSING } from "../format";

export type Lamp = "pass" | "fail" | "unknown" | "idle";

export interface LampDotProps {
  state: Lamp;
  title?: string | undefined;
}

export function LampDot({ state, title }: LampDotProps) {
  return <span className={`lamp lamp--${state}`} title={title} aria-hidden="true" />;
}

export interface ReadoutProps {
  label: string;
  value: string;
  unit?: string | undefined;
  hint?: string | undefined;
  tone?: Lamp | undefined;
  badge?: ReactNode;
}

export function Readout({ label, value, unit, hint, tone, badge }: ReadoutProps) {
  return (
    <div className={`readout ${tone ? `readout--${tone}` : ""}`}>
      <span className="readout__label">{label}</span>
      <span className="readout__value">
        {value}
        {unit ? <>{" "}<span className="readout__unit">{unit}</span></> : null}
      </span>
      {badge ? <span className="readout__badge">{badge}</span> : null}
      {hint ? <span className="readout__hint">{hint}</span> : null}
    </div>
  );
}

export interface FieldProps {
  label: string;
  children: ReactNode;
}

export function Field({ label, children }: FieldProps) {
  return (
    <div className="field">
      <dt className="field__label">{label}</dt>
      <dd className="field__value">{children}</dd>
    </div>
  );
}

export interface FieldsProps {
  children: ReactNode;
}

export function Fields({ children }: FieldsProps) {
  return <dl className="fields">{children}</dl>;
}

export interface EmptyProps {
  children?: ReactNode;
}

export function Empty({ children }: EmptyProps) {
  return <p className="empty">{children ?? `Данные этого блока не передавались (${MISSING})`}</p>;
}

export interface NoteProps {
  children: ReactNode;
  tone?: "plain" | "warn";
}

export function Note({ children, tone = "plain" }: NoteProps) {
  return <p className={`note note--${tone}`}>{children}</p>;
}

export interface TagProps {
  children: ReactNode;
  tone?: Lamp;
}

export function Tag({ children, tone = "idle" }: TagProps) {
  return <span className={`tag tag--${tone}`}>{children}</span>;
}

export interface ScrollerProps {
  label: string;
  children: ReactNode;
}

export function Scroller({ label, children }: ScrollerProps) {
  return (
    <div className="scroller" tabIndex={0} role="group" aria-label={label}>
      {children}
    </div>
  );
}
