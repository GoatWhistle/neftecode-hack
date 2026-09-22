import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { SceneBar } from "./scenes/SceneBar";
import { PRESETS, presetOf } from "./run/presets";
import type { PresetKey } from "./run/presets";
import { WhatIf } from "./whatif/WhatIf";
import { ProtocolBar } from "./whatif/ProtocolBar";
import { RecordBanner } from "./whatif/RecordBanner";
import { PairCompare } from "./compare/PairCompare";
import { TradeoffMapView } from "./compare/TradeoffMap";
import { comparePair } from "./run/pair";
import { buildRecord } from "./run/record";
import type { RunRecord } from "./run/record";
import { ProtocolError, type ParsedProtocol } from "./run/protocol";

const BLANK: Conditions = {
  scenario: "", snapshot: "", fault: "healthy", crude_sulfur_wt_pct: "", product_sulfur_mgkg: "",
  product_t95_c: "", product_cetane_number: "", throughput_tph: "", tank: "", tank_inventory: "",
  tank_available: ""
};

export function App() {
  const [options, setOptions] = useState<RunOptions | null>(null);
  const [conditions, setConditions] = useState<Conditions>(BLANK);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const { run, start, stop, reset, replay, openRecord, adopt, tapeSnapshot, canReplay, pending } = useRun();
  const [pinned, setPinned] = useState<RunRecord | null>(null);
  const [current, setCurrent] = useState<RunRecord | null>(null);
  const [sceneLoading, setSceneLoading] = useState(false);
  const nextLabel = useRef<string | null>(null);
  const built = useRef<unknown>(null);
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

  const startWith = useCallback((frozen: Conditions, label: string | null) => {
    setOpen(null);
    setCurrent(null);
    nextLabel.current = label;
    setLaunched(frozen);
    start(queryOf(frozen));
    scrollToMap();
  }, [start]);

  const launch = useCallback(() => startWith({ ...conditions }, null), [conditions, startWith]);

  const runVariant = useCallback((patch: Partial<Conditions>, base: Conditions) => {
    const next = { ...base, ...patch };
    setConditions(next);
    startWith(next, "Вариант B");
  }, [startWith]);

  const pickPreset = useCallback(async (key: PresetKey) => {
    const preset = PRESETS[key];
    setSceneLoading(true);
    try {
      const next = await requestOptions(preset.scenario);
      if (!next) return;
      const missing = !next.snapshots.some((item) => item.key === preset.snapshot)
        ? `срез ${preset.snapshot} недоступен на сервере`
        : !next.faults.includes(preset.fault) ? `отказ «${preset.fault}» недоступен` : null;
      if (missing) {
        setOptionsError(`Сцена «${preset.label}» не запущена: ${missing}. Подмена другим срезом не выполняется.`);
        return;
      }
      const prepared = conditionsOf(next, preset.fault);
      reset();
      setLaunched(null);
      setCurrent(null);
      setOpen(null);
      setOptions(next);
      setOptionsError(null);
      setConditions({ ...prepared, scenario: preset.scenario, snapshot: preset.snapshot, fault: preset.fault });
    } catch {
      setOptionsError("Сервер условий не ответил: сцена не загружена.");
    } finally {
      setSceneLoading(false);
    }
  }, [requestOptions, reset]);

  useEffect(() => {
    if (run.status !== "done" || !run.live || !run.payload || built.current === run.payload) return;
    built.current = run.payload;
    const shownForm = launched ?? conditions;
    const preset = presetOf(shownForm);
    const label = nextLabel.current ?? (preset ? PRESETS[preset].label : (SCENARIO_LABEL[shownForm.scenario] ?? shownForm.scenario));
    nextLabel.current = null;
    const record = buildRecord({ payload: run.payload, form: shownForm, query: run.query, label,
      tape: tapeSnapshot(), durationMs: run.serverMs });
    setCurrent(record);
    adopt(record);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.status, run.live, run.payload]);

  const openProtocol = useCallback((parsed: ParsedProtocol) => {
    // parseProtocol уже проверил структуру и пробно восстановил и сравнил весь пакет A/B:
    // дальше экран меняется целиком. Исключение здесь — только страховка без частичных изменений.
    const shown = parsed.b ?? parsed.a!;
    try {
      openRecord(shown, parsed.protocol.exported_at);
    } catch {
      throw new ProtocolError("Запись не удалось восстановить: структура файла не соответствует протоколу. Текущий экран сохранён.");
    }
    setPinned(parsed.b ? parsed.a : null);
    setCurrent(shown);
    built.current = shown.payload;
    setOpen(null);
    setLaunched({ ...BLANK, ...(shown.form as Partial<Conditions>) });
    scrollToMap();
  }, [openRecord]);

  const comparison = useMemo(
    () => (pinned && current && pinned.run_id !== current.run_id ? comparePair(pinned, current) : null),
    [pinned, current]
  );

  const reopenConditions = useCallback(() => {
    reset();
    setLaunched(null);
    setCurrent(null);
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
          <SceneBar
            active={presetOf(shown)}
            loading={sceneLoading || options === null}
            running={run.status === "running"}
            ready={options !== null && conditions.scenario !== ""}
            done={run.status === "done"}
            error={run.status === "idle" ? optionsError : null}
            onPreset={(key) => void pickPreset(key)}
            onStart={launch}
            onAdvanced={() => setOpen(INPUT_SCENARIO)}
          >
            <ProtocolBar current={current} pinned={pinned} running={run.status === "running"} onOpen={openProtocol} />
          </SceneBar>
          {run.record ? <RecordBanner info={run.record} /> : null}
          <StatusBar run={run} onStop={stop} onReplay={replay} canReplay={canReplay} />
          {phase !== "idle" && (payload || outcome) ? (
            <div className="answer-slot">
              {outcome ? <OperatorAnswer outcome={outcome} /> : null}
              <WhatIf
                pinned={pinned}
                hasResult={current !== null}
                running={run.status === "running"}
                options={options}
                onPin={() => setPinned(current)}
                onUnpin={() => setPinned(null)}
                onRun={runVariant}
              />
              {comparison && pinned && current ? (
                <PairCompare comparison={comparison} labelA={`A · ${pinned.label}`} labelB={`B · ${current.label}`} />
              ) : null}
            </div>
          ) : null}
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
              {payload ? <Summary payload={payload} state={decisionState} /> : null}
              {payload ? (
                <div className="after__support">
                  <Fold title="Карта компромиссов" hint="выпуск, стоимость и тяжесть допустимых вариантов">
                    <TradeoffMapView payload={payload} />
                  </Fold>
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
