import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PipelineMap } from "../map/PipelineMap";
import { Summary } from "../map/Summary";
import { StatusBar } from "../map/StatusBar";
import { FAULT_LABELS, conditionsOf, fetchOptions, queryOf } from "../run/options";
import type { Conditions, RunOptions } from "../run/options";
import { SCENARIO_LABEL } from "../run/orchRead";
import { ORDER, reachedState } from "../run/sequence";
import { useRun } from "../run/useRun";
import { Logo } from "../ui/Logo";
import { OperatorAnswer } from "../ui/OperatorAnswer";
import "../styles/presentation-mock.css";

type PresetKey = "normal" | "risk" | "bad-data";

interface Preset {
  label: string;
  title: string;
  note: string;
  scenario: string;
  snapshot: string;
  fault: string;
}

const PRESETS: Record<PresetKey, Preset> = {
  normal: {
    label: "Норма",
    title: "Не вмешиваться без причины",
    note: "Устойчивый период: система должна обосновать сохранение режима.",
    scenario: "baseline",
    snapshot: "20260105-080000",
    fault: "healthy"
  },
  risk: {
    label: "Риск качества",
    title: "Найти допустимый компромисс",
    note: "Сернистое сырьё, задержка отклика и ограниченный резерв компонента.",
    scenario: "sour_crude",
    snapshot: "20260724-030000",
    fault: "healthy"
  },
  "bad-data": {
    label: "Плохие данные",
    title: "Отказаться от рискованного совета",
    note: "Лаборатория и поточный анализатор недоступны одновременно.",
    scenario: "baseline",
    snapshot: "20260416-101000",
    fault: "both_broken"
  }
};

const PRESET_ORDER: PresetKey[] = ["normal", "risk", "bad-data"];

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
  if (status === "failed") return "Ошибка прогона";
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

  const selectPreset = useCallback((key: PresetKey) => {
    const preset = PRESETS[key];
    setSelected(key);
    setLoading(true);
    setOptionsError(null);
    setOpen(null);
    stop();
    fetchOptions(preset.scenario)
      .then((next) => {
        const prepared = conditionsOf(next, preset.fault);
        const snapshot = next.snapshots.some((item) => item.key === preset.snapshot)
          ? preset.snapshot
          : prepared.snapshot;
        const fault = next.faults.includes(preset.fault) ? preset.fault : prepared.fault;
        setOptions(next);
        setConditions({ ...prepared, scenario: preset.scenario, snapshot, fault });
      })
      .catch(() => {
        setOptions(null);
        setConditions(BLANK);
        setOptionsError("Сервер условий не ответил. Запустите neftecode serve и повторите запрос.");
      })
      .finally(() => setLoading(false));
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
    start(queryOf(conditions));
  }, [conditions, options, start]);

  const snapshotTitle = useMemo(() => {
    return options?.snapshots.find((item) => item.key === conditions.snapshot)?.title ?? conditions.snapshot;
  }, [conditions.snapshot, options]);

  const inputCaption = useMemo(() => {
    const scenario = SCENARIO_LABEL[conditions.scenario] ?? conditions.scenario;
    const fault = FAULT_LABELS[conditions.fault] ?? conditions.fault;
    return `${scenario || "условия загружаются"} · ${snapshotTitle || "момент не выбран"} · ${fault}`;
  }, [conditions, snapshotTitle]);

  const complete = ORDER.filter((id) => {
    const state = run.stages[id];
    return state === "done" || state === "skipped";
  }).length;
  const running = run.status === "running";
  const provider = payload?.decision.agentic?.provider;
  const model = payload?.decision.agentic?.model;

  return (
    <div className="lr-shell">
      <header className="lr-header">
        <Logo className="lr-logo" />
        <div className="lr-header__copy">
          <strong>Живой цикл принятия решения</strong>
          <span>АВТ → гидроочистка → смешение</span>
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
              {run.status !== "idle" ? <small>{complete} из {ORDER.length} этапов</small> : null}
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
              <strong>{(SCENARIO_LABEL[conditions.scenario] ?? conditions.scenario) || "загружаются"}</strong>
              <small>{snapshotTitle || "момент решения загружается"} · {FAULT_LABELS[conditions.fault] ?? conditions.fault}</small>
            </div>
            {running ? (
              <button type="button" className="lr-stop" onClick={stop}>Остановить</button>
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
            <OperatorAnswer payload={payload} />
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
