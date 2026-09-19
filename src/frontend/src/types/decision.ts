import type { Agentic } from "./agentic";

export * from "./agentic";

export type CheckStatus = "pass" | "fail" | "unknown";

export interface SourceVerdict {
  name: string;
  status: string;
  value: number | null;
  age_hours: number | null;
  max_age_hours: number | null;
  reasons: string[];
  usable: boolean;
}

export interface SuspectValue {
  tag: string;
  value: number | null;
  note: string;
}

export interface TrustReport {
  as_of: string | null;
  usable: boolean;
  primary: string | null;
  fallback: boolean;
  telemetry_missing_fraction: number | null;
  sources: Record<string, SourceVerdict>;
  reasons: string[];
  missing_requirements: string[];
  suspect_values: SuspectValue[];
  rule: string;
  refusal_reason: string | null;
}

export interface GateCheck {
  constraint_id: string;
  status: CheckStatus;
  observed: number | null;
  limit: number | null;
  time_hours: number | null;
  reason: string;
}

export interface Gate {
  plan_id: string | null;
  feasible: boolean;
  checks: GateCheck[];
  first_violation: GateCheck | null;
  unknown_requirements: string[];
  rejection_reasons: string[];
}

export interface PlanStep {
  time_hours: number;
  controls: Record<string, number>;
  recipe: Record<string, number>;
  throughput_tph: number | null;
  additive_dose: number | null;
}

export interface SelectedPlan {
  plan_id: string;
  intent: string;
  changes: number;
  steps: PlanStep[];
}

export interface Alternative {
  candidate_id: string;
  production_t: number | null;
  cost_per_tonne: number | null;
  severity_index: number | null;
  changes: number | null;
  why_not: string;
}

export interface Candidate {
  candidate_id: string;
  controls: Record<string, number>;
  recipe: Record<string, number>;
  throughput_tph: number | null;
  additive_dose: number | null;
  changes: number | null;
  feasible: boolean;
  production_t: number | null;
  cost_per_tonne: number | null;
  severity_index: number | null;
  rejection_reasons: string[];
}

export interface SeverityFactors {
  index: number | null;
  terms: Record<string, number>;
  weights: Record<string, number>;
  reference_temp_c: number | null;
  reference_flow_m3h: number | null;
  control_range_c: number[] | null;
  step_index: number | null;
  reason: string;
  scope: string;
}

export interface TraceEvent {
  agent: string;
  [key: string]: unknown;
}

export interface OptimizerRound {
  round: number;
  proposed: number;
  feasible: number;
  veto_families: Record<string, number>;
  quality_vetoed: number;
  reliability_vetoed: number;
  candidate_ids: string[];
  forbidden_before?: string[];
  restriction_added?: unknown[];
}

export interface RobustnessResult {
  perturbation: string;
  path: string;
  factor: number | null;
  outcome: string;
  reason?: string;
  first_violation?: unknown;
  unknown_requirements?: string[];
  production_t?: number | null;
  cost_per_tonne?: number | null;
}

export interface Robustness {
  plan_id: string | null;
  perturbations_declared: number;
  perturbations_evaluated: number;
  held: number;
  violated: number;
  not_applicable: number;
  share_holding: number | null;
  fragile: boolean;
  results: RobustnessResult[];
  verdict?: string;
  limits?: string[];
}

export interface LookaheadLeg {
  plan_id: string | null;
  lookahead_hours: number | null;
  projected_until_hours: number | null;
  stock_ends_at_hours: number | null;
  hours_to_violation: number | null;
  constraint: string | null;
  observed: number | null;
  limit: number | null;
  assumption: string;
}

export interface Lookahead {
  available: boolean;
  lookahead_hours: number | null;
  min_reaction_hours: number | null;
  initial_plan: string | null;
  initial: LookaheadLeg | null;
  selected: LookaheadLeg | null;
  switched: boolean;
  examined: number;
  warning: string | null;
}

export interface Refusal {
  kind: string;
  examples?: string[];
  missing?: string[];
  [key: string]: unknown;
}

export interface Decision {
  status: string;
  reason: string;
  scope: string | null;
  current_operation: PlanStep | null;
  commercial_release_allowed: boolean;
  scenario_id: string | null;
  selected_plan: SelectedPlan | null;
  immediate_action: PlanStep | null;
  gate: Gate | null;
  production_t: number | null;
  cost_per_tonne: number | null;
  severity_index: number | null;
  alternatives: Candidate[];
  rejected: unknown[];
  refusal: Refusal | null;
  robustness: Robustness | null;
  lookahead: Lookahead | null;
  trace: TraceEvent[];
  note: string | null;
  decision_id: string | null;
  agentic: Agentic | null;
}
