import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PipelineMap } from "../map/PipelineMap";
import { Summary } from "../map/Summary";
import { StatusBar } from "../map/StatusBar";
import { FAULT_LABELS, conditionsOf, fetchOptions, queryOf, sourcesSummary } from "../run/options";
import type { Conditions, RunOptions } from "../run/options";
import { SCENARIO_LABEL } from "../run/orchRead";
import { reachedState } from "../run/sequence";
import { runProgress } from "../run/progress";
import { useRun } from "../run/useRun";
import type { PresetKey } from "../run/presets";
import { PRESETS, PRESET_ORDER } from "../run/presets";
import { Logo } from "../ui/Logo";
import { OperatorAnswer } from "../ui/OperatorAnswer";
import "../styles/presentation-mock.css";

const MODEL_BASIS_LABEL: Record<string, string> = {
  scenario: "сценарий",
  data_beta: "β по данным",
  scenario_kinetics: "кинетика сценария",
  mass_balance: "материальный баланс"
};

const BLANK: Conditions = {
  scenario: "",
  snapshot: "",
  fault: "healthy",
  crude_sulfur_wt_pct: "",
  product_sulfur_mgkg: "",
  product_t95_c: "",
  product_cetane_number: "",
  throughput_tph: "",
  tank: "",
  tank_inventory: "",
  tank_available: ""
};

function statusText(status: string): string {
  if (status === "running") return "Пайплайн работает";
  if (status === "done") return "Расчёт завершён";
  if (status === "failed") return "Расчёт не завершён";
  if (status === "stopped") return "Расчёт остановлен";
  return "Готов к запуску";
}

export function AgentPresentationMock() {
  const [selected, setSelected] = useState<PresetKey>("risk");
  const [options, setOptions] = useState<RunOptions | null>(null);
  const [conditions, setConditions] = useState<Conditions>(BLANK);
  const [loading, setLoading] = useState(true);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const answerRef = useRef<HTMLDivElement | null>(null);
  const pipelineRef = useRef<HTMLElement | null>(null);
  const { run, start, stop, replay, canReplay, pending } = useRun();
  const payload = run.payload;
  const presetRun = useRef(0);
  const presetAbort = useRef<AbortController | null>(null);
  const [launched, setLaunched] = useState<Conditions | null>(null);

  const selectPreset = useCallback((key: PresetKey) => {
    const preset = PRESETS[key];
    setSelected(key);
    setLoading(true);
    setOptionsError(null);
    setOpen(null);
    stop();
    presetRun.current += 1;
    const ticket = presetRun.current;
    presetAbort.current?.abort();
    const controller = new AbortController();
    presetAbort.current = controller;
    fetchOptions(preset.scenario, controller.signal)
      .then((next) => {
        if (ticket !== presetRun.current) return;
        const prepared = conditionsOf(next, preset.fault);
        const snapshot = next.snapshots.some((item) => item.key === preset.snapshot)
          ? preset.snapshot
          : prepared.snapshot;
        const fault = next.faults.includes(preset.fault) ? preset.fault : prepared.fault;
        setOptions(next);
        setConditions({ ...prepared, scenario: preset.scenario, snapshot, fault });
      })
      .catch(() => {
        if (ticket !== presetRun.current || controller.signal.aborted) return;
        setOptions(null);
        setConditions(BLANK);
        setOptionsError("Сервер условий не ответил. Запустите neftecode serve и повторите запрос.");
      })
      .finally(() => {
        if (ticket === presetRun.current) setLoading(false);
      });
  }, [stop]);

  useEffect(() => {
    selectPreset("risk");
  }, [selectPreset]);

  useEffect(() => {
    if (run.status === "running") {
      pipelineRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (run.status === "done") {
      answerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [run.status]);

  const launch = useCallback(() => {
    if (!options || !conditions.scenario) return;
    setOpen(null);
    const frozen: Conditions = { ...conditions };
    setLaunched(frozen);
    start(queryOf(frozen));
  }, [conditions, options, start]);

  const shown = launched ?? conditions;

  const snapshotTitle = useMemo(() => {
    return options?.snapshots.find((item) => item.key === shown.snapshot)?.title ?? shown.snapshot;
  }, [shown.snapshot, options]);

  const inputCaption = useMemo(() => {
    const scenario = SCENARIO_LABEL[shown.scenario] ?? shown.scenario;
    const fault = FAULT_LABELS[shown.fault] ?? shown.fault;
    const sources = sourcesSummary(payload);
    const tail = sources ? ` · ${sources.text}` : "";
    return `${scenario || "условия загружаются"} · ${snapshotTitle || "момент не выбран"} · ${fault}${tail}`;
  }, [shown, snapshotTitle, payload]);

  const progress = runProgress(run, payload);
  const running = run.status === "running";
  const provider = payload?.decision.agentic?.provider;
  const model = payload?.decision.agentic?.model;

  return (
    <div className="lr-shell">
      <header className="lr-header">
        <Logo className="lr-logo" />
        <div className="lr-header__copy">
          <strong>Живой цикл принятия решения</strong>
          {payload?.explanation.chain ? (
            <span>
              {payload.explanation.chain.blocks.map((block, i) => (
                <span key={block.id} title={`${block.controllable_reason} · ${block.model_basis_note}`}>
                  {i > 0 ? " → " : ""}
                  {block.controllable ? block.label : `${block.label} (ходы отключены)`}
                  {" "}
                  ({MODEL_BASIS_LABEL[block.model_basis]})
                </span>
              ))}
            </span>
          ) : (
            <span>АВТ → гидроочистка → смешение</span>
          )}
        </div>
        <a href="/">Расширенные условия</a>
      </header>

      <main className="lr-main">
        <section className="lr-launch" aria-labelledby="launch-title">
          <div className="lr-launch__head">
            <div>
              <p className="lr-kicker">Три обязательные сцены ТЗ</p>
              <h1 id="launch-title">Запустить советчика</h1>
            </div>
            <div className={`lr-run-state lr-run-state--${run.status}`}>
              <i />
              <span>{statusText(run.status)}</span>
              {run.status !== "idle" ? <small>{progress.headline}</small> : null}
            </div>
          </div>

          <div className="lr-presets">
            {PRESET_ORDER.map((key) => {
              const item = PRESETS[key];
              return (
                <button key={key} type="button" className={selected === key ? "is-active" : ""}
                  disabled={running} onClick={() => selectPreset(key)}>
                  <span>{item.label}</span>
                  <strong>{item.title}</strong>
                  <small>{item.note}</small>
                </button>
              );
            })}
          </div>

          <div className="lr-launch__bottom">
            <div className="lr-selected">
              <span>Условия прогона</span>
              <strong>{(SCENARIO_LABEL[shown.scenario] ?? shown.scenario) || "загружаются"}</strong>
              <small>{snapshotTitle || "момент решения загружается"} · {FAULT_LABELS[shown.fault] ?? shown.fault}</small>
            </div>
            {running ? (
              <button type="button" className="lr-stop" onClick={stop}>Остановить отображение</button>
            ) : (
              <button type="button" className="lr-start" disabled={loading || options === null} onClick={launch}>
                {loading ? "Загружаю условия…" : run.status === "done" ? "Запустить ещё раз" : "▶ Запустить пайплайн"}
              </button>
            )}
          </div>

          {optionsError || run.error ? <p className="lr-error" role="alert">{optionsError ?? run.error}</p> : null}
        </section>

        <StatusBar run={run} onStop={stop} onReplay={replay} canReplay={canReplay} />

        {payload ? (
          <div className="lr-answer" ref={answerRef}>
            <OperatorAnswer outcome={{ kind: "result", payload }} />
          </div>
        ) : null}

        <section className="lr-pipeline" ref={pipelineRef} aria-labelledby="pipeline-title">
          <header className="lr-pipeline__head">
            <div>
              <p className="lr-kicker">Фактический поток событий от backend</p>
              <h2 id="pipeline-title">Пайплайн решения</h2>
            </div>
            <div className="lr-pipeline__meta">
              <span>{running && pending ? "соединение с сервером…" : statusText(run.status)}</span>
              {run.agentEvents.length > 0 ? <span>событий агентов: {run.agentEvents.length}</span> : null}
              {provider ? <span>{provider}{model ? ` · ${model}` : ""}</span> : null}
            </div>
          </header>
          <PipelineMap run={run} inputCaption={inputCaption} open={open} onOpen={setOpen} />
        </section>

        {payload ? (
          <details className="lr-details">
            <summary>Открыть полный разбор решения</summary>
            <Summary payload={payload} state={reachedState(run.stages, "decision")} />
          </details>
        ) : null}

        <footer className="lr-foot">
          <span>Экран показывает реальный поток сервера и фактический payload выбранного прогона.</span>
          <span>Сценарные результаты не доказывают промышленный эффект и не разрешают товарный выпуск.</span>
        </footer>
      </main>
    </div>
  );
}
