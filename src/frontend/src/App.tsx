import { useCallback, useEffect, useRef, useState } from "react";
import { ConfigStage } from "./run/ConfigStage";
import { useRun } from "./run/useRun";
import { reachedState } from "./run/sequence";
import type { Conditions, RunOptions } from "./run/options";
import { conditionsOf, conditionsResultOf, FAULT_LABELS, fetchOptions, queryOf, sourcesSummary } from "./run/options";
import { SCENARIO_LABEL } from "./run/orchRead";
import { PipelineMap } from "./map/PipelineMap";
import { INPUT_SCENARIO } from "./map/graph";
import { Summary } from "./map/Summary";
import { AFTER_ID, scrollToConditions, scrollToMap } from "./map/mapRuntime";
import { StatusBar } from "./map/StatusBar";
import { OperatorAnswer } from "./ui/OperatorAnswer";
import { Evidence } from "./evidence/Evidence";
import { PlanCompare } from "./compare/PlanCompare";
import { Fold } from "./graph/Fold";
import { outcomeOf } from "./run/verdict";
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
  const { run, start, stop, reset, replay, canReplay, pending } = useRun();
  const [launched, setLaunched] = useState<Conditions | null>(null);
  const optionsRun = useRef(0);
  const [open, setOpen] = useState<string | null>(null);
  const payload = run.payload;
  const outcome = outcomeOf(run.status, payload, run.error, run.status === "stopped");
  const phase = run.status === "idle" ? "idle" : outcome ? "answer" : "run";
  useDocumentTitle(run);

  const optionsAbort = useRef<AbortController | null>(null);

  const requestOptions = useCallback(
    async (scenario?: string): Promise<RunOptions | null> => {
      optionsAbort.current?.abort();
      const controller = new AbortController();
      optionsAbort.current = controller;
      optionsRun.current += 1;
      const ticket = optionsRun.current;
      try {
        const next = await fetchOptions(scenario, controller.signal);
        if (ticket !== optionsRun.current) return null;
        return next;
      } catch {
        if (ticket !== optionsRun.current || controller.signal.aborted) return null;
        throw new Error("options");
      }
    },
    []
  );

  const loadOptions = useCallback(async (): Promise<boolean> => {
    setOptionsError(null);
    try {
      const next = await requestOptions();
      if (!next) return false;
      setOptions(next);
      setConditions(conditionsOf(next));
      return true;
    } catch {
      return false;
    }
  }, [requestOptions]);

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  const pickScenario = useCallback(
    (name: string) => {
      requestOptions(name)
        .then((next) => {
          if (!next) return;
          setOptions(next);
          setConditions((prev) => {
            const result = conditionsResultOf(next, prev.fault);
            if (result.faultReset && result.previousFault) {
              const label = FAULT_LABELS[result.previousFault] ?? result.previousFault;
              setOptionsError(
                `Отказ «${label}» в этом сценарии недоступен — сброшен на «${FAULT_LABELS.healthy}».`
              );
            } else {
              setOptionsError(null);
            }
            return result.conditions;
          });
        })
        .catch(() => setOptionsError("Сценарий не загружен: сервер условий не ответил."));
    },
    [requestOptions]
  );

  const change = useCallback((patch: Partial<Conditions>) => {
    setConditions((prev) => ({ ...prev, ...patch }));
  }, []);

  const launch = useCallback(() => {
    setOpen(null);
    const frozen: Conditions = { ...conditions };
    setLaunched(frozen);
    start(queryOf(frozen));
    scrollToMap();
  }, [conditions, start]);

  const reopenConditions = useCallback(() => {
    reset();
    setLaunched(null);
    setOpen(null);
    scrollToConditions();
  }, [reset]);

  const decisionState = reachedState(run.stages, "decision");
  const settled = payload !== null && phase === "answer";
  const shown = launched ?? conditions;
  const sources = sourcesSummary(payload);

  const inputCaption = (() => {
    if (!shown.scenario) return "условия не загружены";
    const snapshot = options?.snapshots.find((item) => item.key === shown.snapshot);
    const fault = FAULT_LABELS[shown.fault] ?? shown.fault;
    const scenario = SCENARIO_LABEL[shown.scenario] ?? shown.scenario;
    const tank = options?.defaults.tanks.find((item) => item.id === shown.tank);
    const tankText = tank
      ? tank.on_demand
        ? `${tank.id} — нарабатывают по необходимости`
        : `${tank.id} — ${shown.tank_available === "1" ? "в работе" : "выведен"}`
      : null;
    const parts = [scenario, snapshot?.title ?? shown.snapshot, fault];
    if (tankText) parts.push(tankText);
    if (sources) parts.push(sources.text);
    return parts.join(" · ");
  })();

  const inputMeta =
    run.status === "idle"
      ? "до пуска · условия можно менять"
      : launched
        ? "условия зафиксированы при пуске; поля формы на прогон уже не влияют"
        : "условия зафиксированы на время прогона";

  useEffect(() => {
    if (run.status !== "running" && open === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.querySelector(".ctl__list")) return;
      if (open !== null && open !== INPUT_SCENARIO) {
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
                payload={payload}
              />
            }
          />
          {phase !== "idle" && (settled || (!payload && outcome)) ? (
            <div className="after" id={AFTER_ID} data-phase={phase}>
              {payload ? null : outcome ? (
                <OperatorAnswer outcome={outcome} />
              ) : null}
              {payload ? <Summary payload={payload} state={decisionState} /> : null}
              {payload ? (
                <div className="after__support">
                  <Fold title="Сравнение планов" hint="чем выбранный план лучше отклонённых">
                    <PlanCompare payload={payload} />
                  </Fold>
                  <Fold title="Доказательства" hint="чем подтверждён каждый вывод">
                    <Evidence payload={payload} />
                  </Fold>
                </div>
              ) : null}
            </div>
          ) : null}
        </main>
      </div>

    </div>
  );
}
