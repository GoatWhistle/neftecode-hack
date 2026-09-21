import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ScreenPayload } from "../types";
import type { Conditions } from "./options";
import { buildRecord } from "./record";
import type { RunRecord } from "./record";
import type { RunTape } from "./replay";

export function fixture(name: string): ScreenPayload {
  const path = resolve(process.cwd(), "src/fixtures/pair", `${name}.json`);
  return JSON.parse(readFileSync(path, "utf-8")) as ScreenPayload;
}

export function form(patch: Partial<Conditions> = {}): Conditions {
  return {
    scenario: "sour_crude", snapshot: "20260724-030000", fault: "healthy", crude_sulfur_wt_pct: "",
    product_sulfur_mgkg: "", product_t95_c: "", product_cetane_number: "", throughput_tph: "", tank: "",
    tank_inventory: "", tank_available: "", ...patch
  };
}

export function tapeFor(payload: ScreenPayload): RunTape {
  return {
    frames: [
      { kind: "phase", atMs: 0, phase: { key: "load", label: "Загрузка", detail: "данные", elapsed_ms: 0 } },
      { kind: "stage", atMs: 40, stage: "state", elapsedMs: 40, state: "done", facts: {} },
      { kind: "stage", atMs: 60, stage: "trust", elapsedMs: 60, state: "done", facts: { usable: true } },
      { kind: "tick", atMs: 2500, elapsedMs: 2500 },
      { kind: "screen", atMs: 5200, payload, elapsedMs: 5200 }
    ]
  };
}

export function record(name: string, patch: Partial<Conditions> = {}, label = name): RunRecord {
  const payload = fixture(name);
  return buildRecord({ payload, form: form(patch), query: "?x=1", label, tape: tapeFor(payload), durationMs: 5200 });
}
