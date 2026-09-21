import { runProgress } from "./progress";
import type { RunState } from "./types";

export function RunProgressNote({ run }: { run: RunState }) {
  if (run.status === "stopped") {
    return (
      <p className="progress progress--stopped" role="status">
        Показ остановлен · протокол решения не получен
      </p>
    );
  }
  const progress = runProgress(run, run.payload);
  const detail = [
    progress.ran.length > 0 ? `выполнено: ${progress.ran.map((item) => item.title).join(", ")}` : null,
    progress.skipped.length > 0
      ? `пропущено: ${progress.skipped.map((item) => item.title).join(", ")}`
      : null,
    progress.failed.length > 0
      ? `обрыв: ${progress.failed.map((item) => item.title).join(", ")}`
      : null
  ].filter((part): part is string => part !== null);

  return (
    <details className="progress">
      <summary className="progress__head">{progress.headline}</summary>
      <ul className="progress__list">
        {detail.map((line) => (
          <li key={line} className="progress__item">
            {line}
          </li>
        ))}
      </ul>
    </details>
  );
}
