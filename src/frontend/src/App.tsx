import { useCallback, useEffect, useState } from "react";
import { moment } from "./format";
import { Rail } from "./ui/Rail";
import { useActiveStage } from "./useActiveStage";
import { ConfigStage } from "./run/ConfigStage";
import { RunStrip } from "./run/RunStrip";
import { useRun } from "./run/useRun";
import { stageStateOf } from "./run/types";
import type { Conditions, RunOptions } from "./run/options";
import { conditionsOf, fetchOptions, queryOf } from "./run/options";
import { Pipeline } from "./Pipeline";
import { StageOutline } from "./run/StageOutline";
import { Logo } from "./ui/Logo";
import { useDocumentTitle } from "./useDocumentTitle";

const BLANK: Conditions = {
  scenario: "", snapshot: "", fault: "healthy", crude_sulfur_wt_pct: "", product_sulfur_mgkg: "",
  product_t95_c: "", product_cetane_number: "", throughput_tph: "", tank: "", tank_inventory: "",
  tank_available: ""
};

export function App() {
  const [options, setOptions] = useState<RunOptions | null>(null);
  const [conditions, setConditions] = useState<Conditions>(BLANK);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const { run, start, stop } = useRun();
  const active = useActiveStage(run.status !== "idle");
  const payload = run.payload;
  useDocumentTitle(run);

  useEffect(() => {
    let live = true;
    fetchOptions()
      .then((next) => {
        if (!live) return;
        setOptions(next);
        setConditions(conditionsOf(next));
      })
      .catch((reason: unknown) => {
        if (live) setOptionsError(`Условия прогона не получены: ${String(reason)}`);
      });
    return () => {
      live = false;
    };
  }, []);

  const pickScenario = useCallback((name: string) => {
    fetchOptions(name)
      .then((next) => {
        setOptions(next);
        setConditions(conditionsOf(next));
      })
      .catch((reason: unknown) => setOptionsError(`Сценарий не загружен: ${String(reason)}`));
  }, []);

  const change = useCallback((patch: Partial<Conditions>) => {
    setConditions((prev) => ({ ...prev, ...patch }));
  }, []);

  const launch = useCallback(() => {
    start(queryOf(conditions));
  }, [conditions, start]);

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__text">
          <h1 className="masthead__title">
            <Logo className="masthead__logo" />
          </h1>
          <p className="masthead__sub">
            Советчик оператору цепочки АВТ → гидроочистка → смешение. Путь числа от источника до
            рекомендации: сначала условия, затем восемь этапов по мере того, как сервер их отдаёт.
          </p>
        </div>
        <dl className="masthead__meta">
          <div className="masthead__meta--verdict">
            <dt>Вердикт</dt>
            <dd
              className={`masthead__verdict ${
                payload?.decision.status === "refuse" ? "masthead__verdict--refuse" : ""
              }`}
            >
              {payload ? payload.status_label : "прогона ещё не было"}
            </dd>
          </div>
          <div>
            <dt>Момент решения</dt>
            <dd>{payload ? moment(payload.decision_time) : "—"}</dd>
          </div>
          <div>
            <dt>Сценарий</dt>
            <dd>{payload?.decision.scenario_id ?? (conditions.scenario || "—")}</dd>
          </div>
        </dl>
      </header>

      <div className="layout">
        <Rail payload={payload} active={active} run={run} />
        <main className="stages">
          <ConfigStage
            options={options}
            conditions={conditions}
            status={run.status}
            error={run.error ?? optionsError}
            onChange={change}
            onScenario={pickScenario}
            onStart={launch}
            onReset={stop}
          />
          <RunStrip run={run} />
          {payload ? (
            <Pipeline payload={payload} stateOf={(id) => stageStateOf(run, id)} sources={run.stageSource} agentEvents={run.agentEvents} />
          ) : run.status === "running" ? (
            <StageOutline stateOf={(id) => stageStateOf(run, id)} agentEvents={run.agentEvents} />
          ) : null}
        </main>
      </div>

      <footer className="foot">
        <p>
          Все числа на странице взяты из payload решения без пересчёта. Пустой блок означает, что данных
          не передавали, а не что всё в порядке.
        </p>
      </footer>
    </div>
  );
}
