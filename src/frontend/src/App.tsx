import { useCallback, useEffect, useState } from "react";
import { Rail } from "./ui/Rail";
import { useActiveStage } from "./useActiveStage";
import { ConfigStage } from "./run/ConfigStage";
import { useRun } from "./run/useRun";
import { stageStateOf } from "./run/types";
import type { Conditions, RunOptions } from "./run/options";
import { conditionsOf, conditionsResultOf, FAULT_LABELS, fetchOptions, queryOf } from "./run/options";
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
  const { run, start, stop, pending } = useRun();
  const active = useActiveStage(run.status !== "idle");
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
    start(queryOf(conditions));
  }, [conditions, start]);

  useEffect(() => {
    if (run.status !== "running") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run.status, stop]);

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="masthead__title">
          <Logo className="masthead__logo" />
        </h1>
      </header>

      <div className={`layout ${run.status === "idle" ? "layout--solo" : "layout--railed"}`}>
        {run.status === "idle" ? null : (
          <Rail payload={payload} active={active} run={run} />
        )}
        <main className="stages" aria-live="polite" aria-relevant="additions">
          <ConfigStage
            options={options}
            conditions={conditions}
            status={run.status}
            error={run.error ?? optionsError}
            onChange={change}
            onScenario={pickScenario}
            onStart={launch}
            onReset={stop}
            onRetry={loadOptions}
            pending={pending}
          />
          {payload ? (
            <Pipeline
              payload={payload}
              stateOf={(id) => stageStateOf(run, id)}
              sources={run.stageSource}
              agentEvents={run.agentEvents}
              stages={run.stages}
              stageFacts={run.stageFacts}
              elapsedMs={run.elapsedMs}
              lastFrameAt={run.lastFrameAt}
            />
          ) : run.status === "running" || run.status === "failed" ? (
            <StageOutline
              stages={run.stages}
              stateOf={(id) => stageStateOf(run, id)}
              factsOf={(id) => run.stageFacts[id]}
              agentEvents={run.agentEvents}
              elapsedMs={run.elapsedMs}
              lastFrameAt={run.lastFrameAt}
            />
          ) : null}
        </main>
      </div>

    </div>
  );
}
