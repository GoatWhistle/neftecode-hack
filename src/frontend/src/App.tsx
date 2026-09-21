import { useCallback, useEffect, useState } from "react";
import { ConfigStage } from "./run/ConfigStage";
import { useRun } from "./run/useRun";
import { reachedState } from "./run/sequence";
import type { Conditions, RunOptions } from "./run/options";
import { conditionsOf, conditionsResultOf, FAULT_LABELS, fetchOptions, queryOf } from "./run/options";
import { SCENARIO_LABEL } from "./run/orchRead";
import { PipelineMap } from "./map/PipelineMap";
import { INPUT_SCENARIO } from "./map/graph";
import { Summary } from "./map/Summary";
import { StatusBar } from "./map/StatusBar";
import { OperatorAnswer } from "./ui/OperatorAnswer";
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
  const { run, start, stop, replay, canReplay, pending } = useRun();
  const [open, setOpen] = useState<string | null>(INPUT_SCENARIO);
  const payload = run.payload;
  useDocumentTitle(run);

  const loadOptions = useCallback(async (): Promise<boolean> => {
    setOptionsError(null);
    try {
      const next = await fetchOptions();
      setOptions(next);
      setConditions(conditionsOf(next));
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    let live = true;
    fetchOptions()
      .then((next) => {
        if (!live) return;
        setOptions(next);
        setConditions(conditionsOf(next));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const pickScenario = useCallback((name: string) => {
    fetchOptions(name)
      .then((next) => {
        setOptions(next);
        setConditions((prev) => {
          const result = conditionsResultOf(next, prev.fault);
          if (result.faultReset && result.previousFault) {
            const label = FAULT_LABELS[result.previousFault] ?? result.previousFault;
            setOptionsError(
              `Отказ «${label}» в этом сценарии недоступен — сброшен на «все источники исправны».`
            );
          } else {
            setOptionsError(null);
          }
          return result.conditions;
        });
      })
      .catch(() => setOptionsError("Сценарий не загружен: сервер условий не ответил."));
  }, []);

  const change = useCallback((patch: Partial<Conditions>) => {
    setConditions((prev) => ({ ...prev, ...patch }));
  }, []);

  const launch = useCallback(() => {
    setOpen((current) => (current === INPUT_SCENARIO ? null : current));
    start(queryOf(conditions));
  }, [conditions, start]);

  const reopenConditions = useCallback(() => {
    stop();
    setOpen(INPUT_SCENARIO);
  }, [stop]);

  const inputCaption = (() => {
    if (!conditions.scenario) return "условия не загружены";
    const snapshot = options?.snapshots.find((item) => item.key === conditions.snapshot);
    const fault = FAULT_LABELS[conditions.fault] ?? conditions.fault;
    const scenario = SCENARIO_LABEL[conditions.scenario] ?? conditions.scenario;
    const tank = options?.defaults.tanks.find((item) => item.id === conditions.tank);
    const tankText = tank
      ? tank.on_demand
        ? `${tank.id} — нарабатывают по необходимости`
        : `${tank.id} — ${conditions.tank_available === "1" ? "в работе" : "выведен"}`
      : null;
    const parts = [scenario, snapshot?.title ?? conditions.snapshot, fault];
    if (tankText) parts.push(tankText);
    return parts.join(" · ");
  })();

  const inputMeta =
    run.status === "idle"
      ? "до пуска · условия можно менять"
      : "условия зафиксированы на время прогона";

  useEffect(() => {
    if (run.status !== "running" && open === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.querySelector(".ctl__list")) return;
      if (open !== null) {
        setOpen(null);
        return;
      }
      if (run.status === "running") stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, run.status, stop]);

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="masthead__title">
          <Logo className="masthead__logo" />
        </h1>
      </header>

      <div className="layout">
        <main className="stages" aria-live="polite" aria-relevant="additions">
          <StatusBar run={run} onStop={stop} onReplay={replay} canReplay={canReplay} />
          {payload ? <OperatorAnswer payload={payload} /> : null}
          <PipelineMap
            run={run}
            inputCaption={inputCaption}
            open={open}
            onOpen={setOpen}
            inputMeta={inputMeta}
            inputPanel={
              <ConfigStage
                options={options}
                conditions={conditions}
                status={run.status}
                error={run.error ?? optionsError}
                onChange={change}
                onScenario={pickScenario}
                onStart={launch}
                onReset={stop}
                onReopen={reopenConditions}
                onRetry={loadOptions}
                pending={pending}
              />
            }
          />
          {payload ? <Summary payload={payload} state={reachedState(run.stages, "decision")} /> : null}
        </main>
      </div>

    </div>
  );
}
