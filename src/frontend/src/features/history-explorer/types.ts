export interface HistoryItem {
  snapshot: string;
  at: string;
  label: string;
  synthetic_edits: string[];
  facts: {
    lab_value: number | null;
    lab_sample_time: string | null;
    lab_available_time: string | null;
    pak_value: number | null;
    pak_sample_time: string | null;
    telemetry_missing_fraction: number | null;
  };
  measurements: Record<string, { value: number; time: string; age_min: number } | null>;
  provenance: { model_fingerprint: string | null; source_rules_fingerprint: string | null };
}

export interface HistoryCatalog {
  schema_version: "history.v1";
  timezone: "source-local";
  grid_minutes: number;
  items: HistoryItem[];
  total: number;
  next_offset: number | null;
  snapshot_coverage: { start: string; end: string } | null;
  arbitrary: { available: boolean; reason: string | null };
  note: string;
}

export type HistorySelection = { kind: "snapshot"; snapshot: string; requested_at: string };
