import { useCallback, useId, useMemo, useRef, useState } from "react";
import { JsonView } from "./Json";

const TRUNCATION_MARK = "…";

export interface RawJsonProps {
  label: string;
  text: string;
  full?: string | null;
  serverLimit?: number;
}

interface Reading {
  shown: string;
  value: unknown;
  parsed: boolean;
  cutInShown: boolean;
  restored: boolean;
  restoredBy: number;
}

function parse(text: string): unknown | undefined {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null ? value : undefined;
  } catch {
    return undefined;
  }
}

function read(text: string, full: string | null | undefined): Reading {
  const brief = text.trim();
  const whole = (full ?? "").trim();
  const briefCut = brief.endsWith(TRUNCATION_MARK);
  const useWhole = whole.length > 0 && whole.length >= brief.length;
  const shown = useWhole ? whole : brief;
  const value = parse(shown);
  return {
    shown,
    value: value ?? null,
    parsed: value !== undefined,
    cutInShown: shown.endsWith(TRUNCATION_MARK),
    restored: useWhole && briefCut && whole.length > brief.length,
    restoredBy: useWhole ? whole.length - brief.length : 0
  };
}

function useCopy(text: string) {
  const [state, setState] = useState<"idle" | "done" | "select" | "fail">("idle");
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const select = useCallback(() => {
    const node = bodyRef.current;
    const selection = window.getSelection();
    if (node === null || selection === null) {
      setState("fail");
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
    setState("select");
  }, []);

  const run = useCallback(() => {
    const secure = typeof window !== "undefined" && window.isSecureContext;
    if (secure && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => setState("done"), select);
      return;
    }
    select();
  }, [text, select]);

  return { state, run, bodyRef };
}

const COPY_TEXT: Record<string, string> = {
  idle: "копировать",
  done: "скопировано",
  select: "выделено, Ctrl+C",
  fail: "выделите текст вручную"
};

export function RawJson({ label, text, full, serverLimit = 300 }: RawJsonProps) {
  const reading = useMemo(() => read(text, full), [text, full]);
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const { state, run, bodyRef } = useCopy(reading.shown);

  const size = `${reading.shown.length} символов`;
  const provenance = reading.cutInShown
    ? `сводка обрезана сервером до ${serverLimit} символов — полного текста в ответе нет`
    : reading.restored
      ? `показан полный ответ инструмента: ${size}, сводка в трассе была короче на ${reading.restoredBy}`
      : size;

  return (
    <div className={`orch-raw${open ? " orch-raw--open" : ""}`}>
      <div className="orch-raw__bar">
        <button
          type="button"
          className="orch-raw__toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen(!open)}
        >
          <span className="orch-raw__caret" aria-hidden="true">▸</span>
          <span className="orch-raw__label">{label}</span>
          <span className="orch-raw__kind">{reading.parsed ? "JSON" : "текст"}</span>
        </button>
        {open ? (
          <button type="button" className="orch-raw__copy" onClick={run}>
            {COPY_TEXT[state] ?? COPY_TEXT.idle}
          </button>
        ) : null}
      </div>

      <p className="orch-raw__note">{provenance}</p>

      {open ? (
        <div className="orch-raw__body" id={bodyId} ref={bodyRef}>
          {reading.parsed ? (
            <JsonView value={reading.value} openTo={1} />
          ) : (
            <pre className="orch-raw__text">{reading.shown}</pre>
          )}
          {reading.cutInShown ? (
            <p className="orch-raw__cut">
              {reading.parsed
                ? "конец ответа срезан сервером: показано всё, что дошло"
                : "текст оборван на этом месте сервером, разобрать как JSON не удалось"}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
