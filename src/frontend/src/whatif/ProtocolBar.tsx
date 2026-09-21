import { useRef, useState } from "react";
import type { ParsedProtocol } from "../run/protocol";
import { buildProtocol, parseProtocol, protocolFileName, ProtocolError, serializeProtocol } from "../run/protocol";
import type { RunRecord } from "../run/record";
import "../styles/whatif.css";

interface Props {
  current: RunRecord | null;
  pinned: RunRecord | null;
  running: boolean;
  onOpen: (parsed: ParsedProtocol) => void;
}

export function ProtocolBar({ current, pinned, running, onOpen }: Props) {
  const input = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const download = () => {
    const a = pinned ?? current;
    const b = pinned ? current : null;
    if (!a) return;
    const text = serializeProtocol(buildProtocol(a, b && b.run_id !== a.run_id ? b : null));
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = protocolFileName(a);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setError(null);
    setNote(b && b.run_id !== a.run_id ? "Скачан протокол с парой A/B и списком различий." : "Скачан протокол решения.");
  };

  const open = async (file: File | undefined) => {
    if (!file) return;
    try {
      const parsed = parseProtocol(await file.text());
      setError(null);
      setNote(null);
      onOpen(parsed);
    } catch (reason) {
      setNote(null);
      setError(reason instanceof ProtocolError ? reason.message : "Не удалось прочитать файл протокола");
    } finally {
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="protocol">
      <button type="button" className="protocol__btn" onClick={download} disabled={!current && !pinned}>Скачать протокол</button>
      <button type="button" className="protocol__btn" onClick={() => input.current?.click()} disabled={running}>Открыть запись</button>
      <input ref={input} type="file" accept="application/json,.json" hidden aria-label="Файл протокола решения"
        onChange={(e) => void open(e.target.files?.[0])} />
      {error ? <p className="protocol__msg protocol__msg--error" role="alert">{error}</p> : null}
      {note ? <p className="protocol__msg" role="status">{note}</p> : null}
    </div>
  );
}
