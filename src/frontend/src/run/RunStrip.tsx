import type { RunState } from "./types";

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} с`;
}

export function RunStrip({ run }: { run: RunState }) {
  if (run.status === "idle") return null;

  return (
    <section className="strip" aria-label="Ход расчёта на сервере">
      <div className="strip__head">
        <h2 className="strip__title">
          <span className="strip__tick" aria-hidden="true" />
          Что сейчас делает сервер
        </h2>
        <p className="strip__clock" role="status">
          {run.status === "running" ? "идёт " : "заняло "}
          {seconds(run.serverMs ?? run.elapsedMs)}
        </p>
      </div>

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

      <p className="strip__honest">
        Полоса выше — настоящие отметки времени сервера: приём условий, загрузка сценария, работа ядра
        решения и выдача payload. Ядро решения считает всё за один вызов, поэтому этапы 1–8 ниже
        раскрываются из уже посчитанного payload по мере прихода, а не считаются по одному. Задержка
        между ними — раскрытие результата, а не длительность расчёта.
      </p>
    </section>
  );
}
