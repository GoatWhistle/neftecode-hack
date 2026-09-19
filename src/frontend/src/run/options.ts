export interface SnapshotOption {
  key: string;
  title: string;
}

export interface TankOption {
  id: string;
  inventory: number | null;
  on_demand: boolean;
  available: boolean;
}

export interface RunDefaults {
  crude_sulfur_wt_pct: number | null;
  product_sulfur_mgkg: number | null;
  product_t95_c: number | null;
  product_cetane_number: number | null;
  throughput_tph: number | null;
  tanks: TankOption[];
}

export interface RunOptions {
  scenarios: string[];
  faults: string[];
  snapshots: SnapshotOption[];
  scenario: string;
  snapshot: string;
  defaults: RunDefaults;
}

export interface Conditions {
  scenario: string;
  snapshot: string;
  fault: string;
  crude_sulfur_wt_pct: string;
  product_sulfur_mgkg: string;
  product_t95_c: string;
  product_cetane_number: string;
  throughput_tph: string;
  tank: string;
  tank_inventory: string;
  tank_available: string;
}

export const FAULT_LABELS: Record<string, string> = {
  healthy: "все источники исправны",
  frozen_pak: "поточный анализатор завис",
  stale_lab: "лаборатория устарела",
  both_broken: "лаборатория и анализатор недоступны",
  missing_telemetry: "телеметрия потеряна на 90 %"
};

const EMPTY_DEFAULTS: RunDefaults = {
  crude_sulfur_wt_pct: null,
  product_sulfur_mgkg: null,
  product_t95_c: null,
  product_cetane_number: null,
  throughput_tph: null,
  tanks: []
};

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

export async function fetchOptions(scenario?: string): Promise<RunOptions> {
  const query = scenario ? `?scenario=${encodeURIComponent(scenario)}` : "";
  const response = await fetch(`/api/options${query}`);
  if (!response.ok) throw new Error(`сервер ответил ${response.status}`);
  const data = (await response.json()) as Partial<RunOptions> & { defaults?: Partial<RunDefaults> };
  return {
    scenarios: data.scenarios ?? [],
    faults: data.faults ?? ["healthy"],
    snapshots: data.snapshots ?? [],
    scenario: data.scenario ?? (data.scenarios ?? [])[0] ?? "",
    snapshot: data.snapshot ?? "synthetic",
    defaults: { ...EMPTY_DEFAULTS, ...(data.defaults ?? {}), tanks: data.defaults?.tanks ?? [] }
  };
}

export interface ConditionsResult {
  conditions: Conditions;
  faultReset: boolean;
  previousFault: string | null;
}

export function conditionsOf(options: RunOptions, previousFault?: string): Conditions {
  return conditionsResultOf(options, previousFault).conditions;
}

export function conditionsResultOf(options: RunOptions, previousFault?: string): ConditionsResult {
  const tank = options.defaults.tanks[0];
  const wanted = previousFault ?? "healthy";
  const kept = options.faults.includes(wanted) ? wanted : "healthy";
  const faultReset = wanted !== "healthy" && kept !== wanted;
  return {
    conditions: {
      scenario: options.scenario,
      snapshot: options.snapshot,
      fault: kept,
      crude_sulfur_wt_pct: text(options.defaults.crude_sulfur_wt_pct),
      product_sulfur_mgkg: text(options.defaults.product_sulfur_mgkg),
      product_t95_c: text(options.defaults.product_t95_c),
      product_cetane_number: text(options.defaults.product_cetane_number),
      throughput_tph: text(options.defaults.throughput_tph),
      tank: tank?.id ?? "",
      tank_inventory: text(tank?.inventory ?? null),
      tank_available: tank ? (tank.available ? "1" : "0") : ""
    },
    faultReset,
    previousFault: faultReset ? wanted : null
  };
}

export function queryOf(conditions: Conditions): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(conditions)) {
    if (value !== "") params.set(key, value);
  }
  return `?${params.toString()}`;
}
