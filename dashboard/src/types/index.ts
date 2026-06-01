export interface Span {
  span_id: string
  trace_id: string
  agent_name: string
  span_type: string
  input?: string
  output?: string
  duration_ms?: number
  error_type?: string
  error_message?: string
  server_timestamp: string
}

export interface Alert {
  alert_id: string
  trace_id: string
  agent_name: string
  failure_type: FailureType
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'
  created_at: string
}

export interface PatchProposal {
  proposal_id: string
  alert_id: string
  trace_id: string
  failure_type: FailureType
  patch_type: PatchType
  target_component: string
  explanation: string
  patch_content: string
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  estimated_impact?: string
  root_cause_analysis?: string
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'APPLIED'
  created_at: string
}

export interface EvalRun {
  run_id: string
  patch_id: string
  trace_id: string
  agent_name: string
  before_score: number
  after_score: number
  score_delta: number
  eval_duration_ms: number
  mlflow_run_id?: string
  created_at: string
  failure_type?: FailureType
  patch_type?: PatchType
  target_component?: string
}

export interface AgentHealth {
  agent_name: string
  health_score: number
  eval_count: number
  last_eval_at: string
  last_failure_type?: FailureType
}

export interface TimelineBucket {
  bucket: string
  failure_type: FailureType
  count: number
}

export interface HealthDiff {
  event: 'health_diff'
  agent_name: string
  patch_id: string
  failure_type: FailureType
  before_score: number
  after_score: number
  score_delta: number
  improved: boolean
  mlflow_run_id?: string
  timestamp: string
}

export type FailureType =
  | 'NORMAL'
  | 'HALLUCINATION'
  | 'TOOL_MISFIRE'
  | 'LOOP_DETECTED'
  | 'PLAN_DRIFT'
  | 'CONTEXT_BLEED'

export type PatchType =
  | 'PROMPT_PATCH'
  | 'TOOL_CONFIG_PATCH'
  | 'MEMORY_PATCH'
  | 'RETRY_POLICY_PATCH'

export type WSMessage =
  | { type: 'span'; data: Span }
  | { type: 'alert'; data: Alert }
  | { type: 'patch_proposal'; data: PatchProposal }
  | { type: 'health_diff'; data: HealthDiff | AgentHealth }
  | { type: 'ping'; ts: string }
