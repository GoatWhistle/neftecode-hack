import type { HistoryCatalog } from "./types";

/** Тестовый каталог формы history.v1 (для компонентных тестов). */
export const catalog: HistoryCatalog = {
  schema_version: "history.v1", timezone: "source-local", grid_minutes: 10,
  total: 1, next_offset: null, snapshot_coverage: null,
  arbitrary: { available: false, reason: "нет task/" }, note: "Наблюдавшиеся условия",
  items: [{ snapshot: "20260703-111000", at: "2026-07-03T11:10:00", label: "Срез из поставки",
    synthetic_edits: [], facts: { lab_value: null, pak_value: 8, telemetry_missing_fraction: null,
      lab_sample_time: null, lab_available_time: null, pak_sample_time: null },
    measurements: {}, provenance: { model_fingerprint: null, source_rules_fingerprint: null } }]
};
