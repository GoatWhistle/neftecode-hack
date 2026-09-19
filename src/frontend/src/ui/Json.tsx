import { useMemo, useState } from "react";

type Json = unknown;

function kindOf(value: Json): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function scalarText(value: Json): string {
  if (typeof value === "string") return `"${value}"`;
  return String(value);
}

function summary(value: Json): string {
  if (Array.isArray(value)) return `[ ${value.length} ]`;
  const keys = Object.keys(value as object);
  return `{ ${keys.length} }`;
}

interface NodeProps {
  name: string | null;
  value: Json;
  depth: number;
  openTo: number;
}

function JsonNode({ name, value, depth, openTo }: NodeProps) {
  const [open, setOpen] = useState(depth < openTo);
  const kind = kindOf(value);
  const label = name === null ? null : <span className="json__key">{name}</span>;

  if (kind !== "object" && kind !== "array") {
    return (
      <div className="json__row" style={{ paddingLeft: `${depth * 14}px` }}>
        {label}
        {label ? <span className="json__colon">:</span> : null}
        <span className={`json__scalar json__scalar--${kind}`}>{scalarText(value)}</span>
      </div>
    );
  }

  const entries: Array<[string, Json]> = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value as Record<string, Json>);

  return (
    <div className="json__branch">
      <button
        type="button"
        className="json__toggle"
        style={{ paddingLeft: `${depth * 14}px` }}
        aria-expanded={open}
        aria-label={`${name ?? "корень"}, ${summary(value)}`}
        onClick={() => setOpen(!open)}
      >
        <span className="json__caret" aria-hidden="true">▸</span>
        {label}
        {label ? <span className="json__colon">:</span> : null}
        <span className="json__summary">{summary(value)}</span>
      </button>
      {open ? (
        <div className="json__children">
          {entries.map(([key, item]) => (
            <JsonNode key={key} name={key} value={item} depth={depth + 1} openTo={openTo} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export interface JsonViewProps {
  value: Json;
  openTo?: number;
}

export function JsonView({ value, openTo = 1 }: JsonViewProps) {
  return (
    <div className="json">
      <JsonNode name={null} value={value} depth={0} openTo={openTo} />
    </div>
  );
}

export interface JsonPanelProps {
  title: string;
  value: Json;
  openTo?: number;
  defaultOpen?: boolean;
}

export function JsonPanel({ title, value, openTo = 1, defaultOpen = false }: JsonPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const size = useMemo(() => `${(new Blob([text]).size / 1024).toFixed(1)} КБ`, [text]);

  return (
    <div className={`panel ${open ? "panel--open" : ""}`}>
      <button type="button" className="panel__head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="panel__caret" aria-hidden="true">▸</span>
        <span className="panel__title">{title}</span>
        <span className="panel__size">{size}</span>
      </button>
      {open ? (
        <div className="panel__body">
          <JsonView value={value} openTo={openTo} />
        </div>
      ) : null}
    </div>
  );
}
