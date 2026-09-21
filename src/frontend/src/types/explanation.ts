import type { Alternative } from "./decision";

export interface Evidence {
  kind: string;
  ref: string;
  value: number | null;
  detail: string;
}

export interface Statement {
  topic: string;
  text: string;
  value: number | null;
  evidence: Evidence[];
}

export interface OperationOrigin {
  controls: Record<string, string>;
  recipe: string;
  throughput_tph: string;
  additive_dose: string;
}

export interface CurrentOperation {
  controls: Record<string, number>;
  recipe: Record<string, number>;
  throughput_tph: number | null;
  additive_dose: number | null;
  origin: OperationOrigin | null;
}

export interface Warning {
  kind: string;
  text: string;
  observed_margin_mgkg?: number;
  operating_margin_mgkg?: number;
}

export interface RiskItem {
  kind: string;
  level: string;
  text: string;
  missing?: string[];
  sources?: string[];
  perturbations?: string[];
}

export interface Risk {
  level: string;
  items: RiskItem[];
  headline: string;
  scope: string;
}

export interface NextStep {
  need: string;
  kind: string;
  available_in_hours?: number | null;
  caveat?: string;
}

export interface StepOrigin {
  time_hours: number;
  controls: Record<string, string | null>;
  recipe: string | null;
  throughput_tph: string | null;
  additive_dose: string | null;
}

export interface PlanOrigin {
  immediate_action: StepOrigin | null;
  steps: StepOrigin[];
  rule: string;
}

export interface ChainBlock {
  id: "avt" | "hydrotreating" | "blending";
  label: string;
  controllable: boolean;
  controllable_reason: string;
  controls: Record<string, boolean>;
  model_basis: "scenario" | "data_beta" | "scenario_kinetics" | "mass_balance";
  model_basis_note: string;
  beta_mgkg_per_c?: number;
}

export interface Chain {
  mode: "live" | "scenario";
  blocks: ChainBlock[];
}

export interface Explanation {
  status: string;
  reason: string;
  kind?: string;
  statements?: Statement[];
  next_steps?: NextStep[];
  current_operation: CurrentOperation | null;
  component_names: Record<string, string>;
  warnings?: Warning[];
  risk: Risk | null;
  checks_passed?: number;
  checks_total?: number;
  alternatives?: Alternative[];
  comparison_rule?: string;
  limits: string[];
  plan_origin?: PlanOrigin | null;
  chain?: Chain | null;
}

export interface ForecastPoint {
  time_hours: number;
  value: number;
  low?: number;
  high?: number;
}

export interface Forecast {
  property?: string;
  unit?: string;
  limit?: number | null;
  points?: ForecastPoint[];
  note?: string;
  [key: string]: unknown;
}
