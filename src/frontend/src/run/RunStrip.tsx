import type { RunState } from "./types";

function seconds(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  return `${(ms / 1000).toFixed(1).replace(".", ",")} с`;
}

export interface RunStripProps {
  run: RunState;
  followsUser?: boolean;
  onResumeFollow?: () => void;
}

export function RunStrip({ run, followsUser, onResumeFollow }: RunStripProps) {
  if (run.status === "idle") return null;
  const done = run.status === "done";

  return (
    <section
      className={`strip ${done ? "strip--done" : ""}`}
      aria-label="Ход расчёта на сервере"
    >
      <div className="strip__head">
        <h2 className="strip__title">
          <span className="strip__tick" aria-hidden="true" />
          {done ? "Сервер закончил" : "Что сейчас делает сервер"}
        </h2>
        <div className="strip__aside">
          {followsUser && run.status === "running" ? (
            <button type="button" className="strip__follow" onClick={onResumeFollow}>
              Следить за этапами
            </button>
          ) : null}
          <p className="strip__clock" role="status">
            {run.status === "running" ? "идёт " : "заняло "}
            {seconds(run.serverMs ?? run.elapsedMs)}
          </p>
        </div>
      </div>

      {run.phases.length === 0 && run.status !== "failed" ? (
        <p className="strip__waiting">Ответа сервера ещё не было: показывать здесь нечего.</p>
      ) : (
        <ol className="strip__phases">
          {run.phases.map((phase) => (
            <li key={phase.key} className={`strip__phase strip__phase--${phase.state}`}>
              <span className="strip__label">{phase.label}</span>
              <span className="strip__detail">{phase.detail}</span>
              <span className="strip__at">{seconds(phase.elapsedMs)}</span>
            </li>
          ))}
          {run.status === "failed" ? (
            <li className="strip__phase strip__phase--failed">
              <span className="strip__label">Расчёт прерван</span>
              <span className="strip__detail">{run.error}</span>
              <span className="strip__at">{seconds(run.elapsedMs)}</span>
            </li>
          ) : null}
        </ol>
      )}
    </section>
  );
}
