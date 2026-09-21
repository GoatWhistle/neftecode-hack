import { useMemo, useState } from "react";
import type { Conditions, RunOptions } from "../run/options";
import { FAULT_LABELS } from "../run/options";
import type { RunRecord } from "../run/record";
import "../styles/whatif.css";

export interface QuickChange {
  patch: Partial<Conditions>;
  summary: string[];
}

interface Props {
  pinned: RunRecord | null;
  hasResult: boolean;
  running: boolean;
  options: RunOptions | null;
  onPin: () => void;
  onUnpin: () => void;
  onRun: (patch: Partial<Conditions>, base: Conditions) => void;
}

function baseOf(record: RunRecord): Conditions {
  const f = record.form as Partial<Conditions>;
  return {
    scenario: f.scenario ?? "", snapshot: f.snapshot ?? "", fault: f.fault ?? "healthy",
    crude_sulfur_wt_pct: f.crude_sulfur_wt_pct ?? "", product_sulfur_mgkg: f.product_sulfur_mgkg ?? "",
    product_t95_c: f.product_t95_c ?? "", product_cetane_number: f.product_cetane_number ?? "",
    throughput_tph: f.throughput_tph ?? "", tank: f.tank ?? "", tank_inventory: f.tank_inventory ?? "",
    tank_available: f.tank_available ?? ""
  };
}

export function quickChangeOf(base: Conditions, draft: { fault: string; tank: string; available: string; throughput: string },
  tanks: Array<{ id: string; available: boolean; inventory: number | null }>): QuickChange {
  const patch: Partial<Conditions> = {};
  const summary: string[] = [];
  if (draft.fault !== base.fault) {
    patch.fault = draft.fault;
    summary.push(`Отказ источника: ${FAULT_LABELS[base.fault] ?? base.fault} → ${FAULT_LABELS[draft.fault] ?? draft.fault}`);
  }
  const current = tanks.find((t) => t.id === (base.tank || tanks[0]?.id));
  const currentAvailable = base.tank_available === "" ? (current?.available ? "1" : "0") : base.tank_available;
  if (draft.tank && (draft.tank !== (base.tank || tanks[0]?.id) || draft.available !== currentAvailable)) {
    const target = tanks.find((t) => t.id === draft.tank);
    if (draft.tank !== base.tank) {
      patch.tank = draft.tank;
      patch.tank_inventory = target?.inventory === null || target?.inventory === undefined ? "" : String(target.inventory);
    }
    patch.tank_available = draft.available;
    summary.push(`Резервуар ${draft.tank}: ${draft.available === "1" ? "в работе" : "выведен"}`);
  }
  if (draft.throughput.trim() !== "" && draft.throughput.trim() !== base.throughput_tph) {
    patch.throughput_tph = draft.throughput.trim();
    summary.push(`Производительность: ${base.throughput_tph || "по сценарию"} → ${draft.throughput.trim()} т/ч`);
  }
  return { patch, summary };
}

export function WhatIf({ pinned, hasResult, running, options, onPin, onUnpin, onRun }: Props) {
  const tanks = useMemo(() => {
    const defaults = pinned?.payload.defaults?.tanks ?? options?.defaults.tanks ?? [];
    return defaults;
  }, [pinned, options]);
  const base = pinned ? baseOf(pinned) : null;
  const [fault, setFault] = useState<string | null>(null);
  const [tank, setTank] = useState<string | null>(null);
  const [available, setAvailable] = useState<string | null>(null);
  const [throughput, setThroughput] = useState("");

  if (!pinned || !base) {
    return (
      <section className="whatif" aria-labelledby="whatif-title">
        <h3 className="whatif__title" id="whatif-title">Что изменится, если…</h3>
        <p className="whatif__lead">Закрепите этот результат как исходный (A), затем измените одно условие и пересчитайте: результаты встанут рядом.</p>
        <button type="button" className="whatif__btn" onClick={onPin} disabled={!hasResult || running}>
          Закрепить для сравнения
        </button>
      </section>
    );
  }
  const tankId = tank ?? (base.tank || tanks[0]?.id || "");
  const tankNow = tanks.find((t) => t.id === tankId);
  const availableNow = available ?? (tankId === (base.tank || tanks[0]?.id)
    ? (base.tank_available === "" ? (tankNow?.available ? "1" : "0") : base.tank_available)
    : (tankNow?.available ? "1" : "0"));
  const draft = { fault: fault ?? base.fault, tank: tankId, available: availableNow, throughput };
  const change = quickChangeOf(base, draft, tanks);
  const faults = options?.faults ?? Object.keys(FAULT_LABELS);
  const canRun = change.summary.length > 0 && !running;

  return (
    <section className="whatif" aria-labelledby="whatif-title">
      <div className="whatif__head">
        <h3 className="whatif__title" id="whatif-title">Что изменится, если…</h3>
        <p className="whatif__pinned">Закреплён A: <b>{pinned.label}</b>{pinned.origin === "record" ? " · запись" : ""}
          <button type="button" className="whatif__link" onClick={onUnpin} disabled={running}>открепить</button>
          {hasResult ? <button type="button" className="whatif__link" onClick={onPin} disabled={running}>закрепить текущий результат вместо A</button> : null}
        </p>
      </div>
      <p className="whatif__lead">Остальные условия остаются как в A (сценарий, срез, прочие поля). Поддерживаются только изменения, которые понимает сервер.</p>
      <div className="whatif__fields">
        <label className="whatif__field">
          <span>Внесённый отказ источника</span>
          <select value={draft.fault} onChange={(e) => setFault(e.target.value)} disabled={running}>
            {faults.map((f) => <option key={f} value={f}>{FAULT_LABELS[f] ?? f}</option>)}
          </select>
          <small>Это модельная инъекция, не оценка исправности прибора.</small>
        </label>
        {tanks.length > 0 ? (
          <label className="whatif__field">
            <span>Резервуар</span>
            <span className="whatif__pair">
              <select aria-label="Резервуар" value={tankId} onChange={(e) => { setTank(e.target.value); setAvailable(null); }} disabled={running}>
                {tanks.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}
              </select>
              <select aria-label="Доступность резервуара" value={availableNow} onChange={(e) => setAvailable(e.target.value)}
                disabled={running || tankNow?.on_demand === true}>
                <option value="1">в работе</option>
                <option value="0">выведен</option>
              </select>
            </span>
            {tankNow?.on_demand ? <small>Компонент нарабатывают по необходимости: доступность не задаётся.</small> : null}
          </label>
        ) : null}
        <label className="whatif__field">
          <span>Производительность, т/ч</span>
          <input type="number" inputMode="decimal" value={throughput} placeholder={base.throughput_tph || "по сценарию"}
            onChange={(e) => setThroughput(e.target.value)} disabled={running} />
        </label>
      </div>
      <p className="whatif__summary" aria-live="polite">
        {change.summary.length === 0 ? "Измените хотя бы одно условие." : `Изменится: ${change.summary.join("; ")}.`}
      </p>
      <button type="button" className="whatif__btn" disabled={!canRun}
        onClick={() => onRun(change.patch, base)}>
        Пересчитать с изменением (B)
      </button>
    </section>
  );
}
