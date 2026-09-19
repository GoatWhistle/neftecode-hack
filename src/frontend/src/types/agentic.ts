export interface OpinionReason {
  code: string;
  text: string;
  candidate_id?: string | null;
}

export interface ProposedConstraint {
  type: string;
  limit?: string | null;
  value?: number | null;
}

export interface AgentOpinion {
  role: string;
  verdict: string;
  risk_level: string | null;
  confidence: number | null;
  valid: boolean;
  reasons: OpinionReason[];
  candidate_verdicts?: Record<string, string>;
  proposed_constraints?: ProposedConstraint[];
  preferred_candidates?: string[];
}

export interface AgenticFinal {
  action: string;
  candidate_id: string | null;
  reason_codes: string[];
  summary: string;
  evidence_refs?: string[];
}

export interface AgenticBudget {
  llm_calls?: number;
  max_llm_calls?: number;
  llm_calls_by_role?: Record<string, number>;
  replans?: number;
  consults?: Record<string, number>;
  robustness_runs?: number;
  usage?: Record<string, number>;
}

export interface Agentic {
  mode: string;
  outcome: string;
  fallback_reason: string | null;
  legacy_decision_id: string | null;
  legacy_status: string | null;
  provider: string | null;
  model: string | null;
  note: string;
  deterministic_policy?: boolean;
  provider_label?: string;
  opinions?: AgentOpinion[];
  llm_choice_overridden?: boolean;
  vetoed_candidates?: Record<string, string[]>;
  constraints_applied?: ProposedConstraint[];
  final?: AgenticFinal | null;
  budget?: AgenticBudget;
  trace?: unknown[];
}
