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
  controls?: Record<string, number> | undefined;
  recipe?: Record<string, number> | undefined;
  throughput_tph?: number | null | undefined;
  additive_dose?: number | null | undefined;
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

export interface SelectionPolicy {
  ranking: string[];
  severity_cost_tolerance_fraction: number | null;
  max_severity_index: number | null;
  reliability_tradeoff: unknown;
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
  mandatory_declared?: number;
  mandatory_evaluated?: number;
  mandatory_failed?: number;
  mandatory_failure_names?: string[];
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

export interface LookaheadOffspec {
  available?: boolean;
  share: number | null;
  share_source?: string | null;
  main_tank?: string | null;
  main_stock_t: number | null;
  main_price_per_t: number | null;
  rework_cost: number | null;
  hold_cost_per_tonne: number | null;
  plan_cost_per_tonne: number | null;
  delta_cost_per_tonne: number | null;
  production_t: number | null;
  plan_extra_cost: number | null;
  affects_admissibility: boolean;
  note: string | null;
  hold_feasible: boolean | null;
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
  offspec?: LookaheadOffspec | null;
}

export interface Refusal {
  kind: string;
  examples?: string[];
  missing?: string[];
  [key: string]: unknown;
}

export interface DeploymentInput {
  id: string;
  label: string;
  status: "open" | "given";
  unit: string;
  required_values: string[];
  scenario_assumptions: Record<string, number | null>;
  impact: string;
}

export interface DeploymentReadiness {
  ready: boolean;
  reason: string;
  required_inputs: DeploymentInput[];
}

export interface SeverityComponent {
  term: string;
  excess: number;
  unit: string;
  scale: number;
  value: number;
  weight: number;
  contribution: number;
}

export interface SeverityLimit {
  kind: "passport" | "model_region" | "scenario";
  label: string;
  known: boolean;
  unit?: string;
  bounds?: number[];
  bound?: number;
  headroom?: number;
  max_severity_index?: number;
  index_headroom?: number;
  note: string;
}

export interface SeverityProfileInfo {
  version: string;
  source: string;
  origin: string;
  reference_temp_c: number;
  temp_scale_c: number;
  reference_flow_m3h: number;
  flow_scale_m3h: number;
  applicability: string;
}

export interface SeverityMode {
  available: boolean;
  index: number | null;
  reason?: string;
  components?: SeverityComponent[];
  profile_version?: string;
  profile_id?: string;
  profile?: SeverityProfileInfo;
  temp_c?: number;
  flow_m3h?: number;
  limits?: SeverityLimit[];
  scope?: string;
}

export interface SeverityBlock {
  current: SeverityMode | null;
  selected: SeverityMode | null;
  current_inputs_origin?: Record<string, string>;
  comparable: boolean;
  delta: number | null;
  rule: string;
}

export interface TradeoffPoint {
  candidate_id: string;
  production_t: number;
  cost_per_tonne: number;
  severity_index: number;
  changes: number;
  on_front: boolean;
  dominated_by: string | null;
  selected: boolean;
  is_hold: boolean;
  recipe: Record<string, number>;
  throughput_tph: number | null;
  additive_dose: number | null;
  moves: Array<{ name: string; from: number; to: number }>;
  gate_passed: boolean;
  stress_checked: boolean;
  robustness?: Record<string, number | boolean | null> | null;
  equivalent_count: number;
  equivalent_ids: string[];
}

export interface TradeoffMap {
  version: string;
  status: "ok" | "empty" | "unknown_metrics";
  criteria: Array<{ key: string; label: string; unit: string; goal: "min" | "max" }>;
  precision: number;
  horizon_hours: number | null;
  severity_profile: string | null;
  pool: {
    admissible: number;
    comparable: number;
    front: number;
    front_distinct: number;
    dominated: number;
    distinct_points: number;
    excluded_unknown: Array<{ candidate_id: string; missing: string[] }>;
    excluded_unknown_count: number;
    points_shown: number;
    points_truncated: boolean;
    evaluated: number | null;
    search_budget: number | null;
    rounds: number | null;
  };
  selected_id: string | null;
  selected_on_front: boolean | null;
  selection_note: string | null;
  selection_reason: string | null;
  hold: { id: string; admissible: boolean; note: string | null };
  points: TradeoffPoint[];
  scope: string;
  stress_scope: string;
}

export interface ConsequencePoint {
  t: number;
  value: number | null;
  status: CheckStatus;
}

export interface ConsequenceCandidateSeries {
  candidate_id: string;
  points: ConsequencePoint[];
}

export interface ConsequenceSeries {
  limit_id: string;
  quality: string;
  unit: string | null;
  direction: "max" | "min" | "unknown";
  limit: { value: number | null; source: string | null };
  candidates: {
    selected: ConsequenceCandidateSeries;
    hold?: ConsequenceCandidateSeries;
  };
}

export interface ConsequenceApplicabilityPoint {
  t: number;
  value: string;
}

export interface Consequences {
  version: number;
  selected_id: string;
  horizon_hours: number;
  step_hours: number;
  series: ConsequenceSeries[];
  applicability: {
    selected: ConsequenceApplicabilityPoint[];
    hold?: ConsequenceApplicabilityPoint[];
  };
  hold: {
    available: boolean;
    candidate_id: string | null;
    source: string | null;
    reason: string | null;
  };
  note: string;
}

export interface Decision {
  status: string;
  reason: string;
  scope: string | null;
  current_operation: PlanStep | null;
  commercial_release_allowed: boolean;
  deployment_readiness?: DeploymentReadiness;
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
  selection_policy: SelectionPolicy | null;
  trace: TraceEvent[];
  note: string | null;
  decision_id: string | null;
  agentic: Agentic | null;
  severity?: SeverityBlock | null;
  tradeoff?: TradeoffMap | null;
  consequences?: Consequences | null;
}
