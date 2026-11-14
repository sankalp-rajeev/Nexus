// Types and loader for dashboard/public/replay.json (schema version 2), written by
// dashboard/scripts/export_replay.py from recorded DEV evidence.

export type Outcome = 'pass' | 'fail' | 'skipped'

export interface ReplaySpan {
  span_id: string
  parent_span_id?: string
  span_type: string
  agent_name?: string
  input?: string
  input_chars?: number
  output?: string
  output_chars?: number
  duration_ms?: number
  error_type?: string
  error_message?: string
  client_timestamp?: string
  metadata?: Record<string, unknown>
}

export interface DetectorVerdict {
  verdict: string
  dev_label: string
  agrees_with_dev_label: boolean | null
  nli: { ran: boolean; score: number | null; flag: boolean }
  entity_rule: unknown
  threshold: Record<string, unknown> | null
  evidence: { span_id: string; step: number; text: string; text_chars?: number } | null
}

export interface ReplayTrace {
  trace_id: string
  view_id: string
  agent_name: string
  task_id: string
  family: string
  started_at: string | null
  root_input: string | null
  root_input_chars?: number
  final_output: string | null
  final_output_chars?: number
  detector: DetectorVerdict
  spans: ReplaySpan[]
}

export interface GateCheck {
  id: 'repair' | 'heldout' | 'regression'
  label: string
  rule: string
  outcome: Outcome
  stage_seconds: number
  detail: string | null
  facts: Record<string, unknown>
}

export interface CriticBlock {
  status: 'patch' | 'no_patch' | 'not_called'
  reason?: string | null
  provider?: string
  model?: string
  model_version?: string
  prompt_version?: string
  source?: string
  temperature?: number
  patch_type?: string
  target_component?: string
  confidence?: string
  diagnosed_failure_type?: string
  cited_span_id?: string
  cited_step?: number
  explanation?: string
  root_cause_analysis?: string
  estimated_impact?: string
  patch_content?: string
  patch_content_chars?: number
  diff?: string | null
  dry_run_applied?: boolean
  critic_notes?: string[]
  usage?: { input_tokens?: number; output_tokens?: number; latency_ms?: number; cost_usd?: number }
}

export interface ReplayHeal {
  heal_id: string
  run: 'main' | 'gemini'
  run_label: string
  category: string
  selected_because: string
  trace_id: string
  task_id: string
  family: string
  dev_label: string
  fault: string
  detector_failure_class: string
  detector: DetectorVerdict
  critic: CriticBlock
  gate: { checks: GateCheck[]; decision: 'promoted' | 'rejected'; reason: string; promoted: boolean }
  timing: { total_s: number; stages_s: Record<string, number> }
  cost: { provider_usd?: number; input_tokens?: number; output_tokens?: number }
  paired_headline_run?: { decision: string; source: string }
  source: { run: string; record: string; record_sha256: string; item_sha256: string; execution_commit?: string; frozen_reference?: string }
}

export interface HeadlineItem {
  id: string
  label: string
  value: string
  scope: string
  note?: string
  source: { path: string; locator: string }
}

interface HeroProofBase {
  id: string
  split: 'test' | 'dev'
  scope: string
  source: { path: string; locator: string }
  /** The committed report row a reader should land on. */
  cite: { path: string; line: number }
}

/** A count k out of n, e.g. the 12 of 36 genuine patches that broke a passing task. */
export interface HeroFraction extends HeroProofBase {
  kind: 'fraction'
  k: number
  n: number
  wilson95: [number, number] | null
  /** Where the term is defined (the preregistration), when the label uses a defined term. */
  definition?: { path: string; line: number }
}

/** A measured value beside the baseline it replaced, e.g. macro recall vs the old classifier. */
export interface HeroComparison extends HeroProofBase {
  kind: 'comparison'
  value: number
  baseline: number
  /** How many failure classes the macro average runs over. */
  classes: number
}

export interface Count { k: number; n: number; wilson95: [number, number] | null }

/** A figure printed by the story sections; arms are named per figure (critic/generic, dev/test, ...). */
export interface StoryFigure extends HeroProofBase {
  kind: 'versus' | 'values'
  unit?: string
  values?: Record<string, number>
  interval_note?: string | null
  classes?: string[]
  critic?: Count
  generic?: Count
  no_patch?: Count
  dev?: Count
  test?: Count
}

export type HeroProof = HeroFraction | HeroComparison

export interface TrailMetric {
  numerator: number; denominator: number; estimate: number | null
  wilson95: [number, number] | null
}
export interface TrailRow {
  cohort: 'TRAIL-A' | 'TRAIL-B'; version: 'v1' | 'v2'; class_name: string
  mapping: 'primary' | 'C3_secondary'; cohort_denominator: number; evaluated: number
  tp: number; fp: number; fn: number; tn: number; gold_positive: number; cohort_gold_positive: number | null
  precision: TrailMetric; recall: TrailMetric; abstentions: Record<string, number>; exclusions: Record<string, number>
  source: string
}
export interface ExternalTrail {
  aggregate_only: true; rows: TrailRow[]
  dataset: { name: string; traces: number; license: string; gated: boolean; card: string }
  guardrail: { independent_macro_v1: number; independent_macro_v2: number; priority_macro_v1: number
    priority_macro_v2: number; priority_macro_drop: number; drop_limit: number; masked_misfires: number; v2_live_candidate: boolean }
  claims: { primary_hypothesis: string; loop_dev_precision: number; loop_dev_recall: number; misfire_min_positives: number
    hallucination_dev_precision: number; hallucination_dev_recall: number; hallucination_improvement_claim: boolean }
  sources: { A: string; B: string; development: string; protocol: string }
}

export interface ReplayData {
  schema_version: 2
  mode: 'replay'
  split: 'dev'
  read_only: true
  notices: string[]
  provenance: {
    generated_from_commit: string
    repository: string
    exporter: string
    data_statement: string
    selection_rule: { traces: string; heals: string; heal_rules: { rule: string; run: string; describes: string }[] }
    selected_trace_ids_by_rule: string[]
    sources: Record<string, string>
    phase5_runs: Record<string, unknown>
    phase5_runs_location: string
    llm_calls: number
  }
  headline: { groups: { title: string; items: HeadlineItem[] }[]; hero: { proof: HeroProof[] }; story: { figures: StoryFigure[] } }
  traces: ReplayTrace[]
  heals: ReplayHeal[]
  external_trail?: ExternalTrail
}

export const STAGES = ['Detect', 'Propose', 'Repair check', 'Held-out check', 'Regression check', 'Decision'] as const

/** Link to a source file at the exact commit the replay was exported from. */
export function sourceUrl(data: ReplayData, path: string): string {
  return `${data.provenance.repository}/blob/${data.provenance.generated_from_commit}/${path}`
}

export function validateReplay(data: any): ReplayData {
  const lists = ['notices', 'traces', 'heals']
  if (!data || data.schema_version !== 2 || data.mode !== 'replay' || data.split !== 'dev' || data.read_only !== true ||
      !lists.every(key => Array.isArray(data[key])) || !data.provenance || !data.headline?.groups) {
    throw new Error('Unsupported replay export: expected read-only DEV schema version 2')
  }
  return data as ReplayData
}

export async function loadReplay(): Promise<ReplayData> {
  const response = await fetch(`${import.meta.env.BASE_URL}replay.json`)
  if (!response.ok) throw new Error(`Replay export unavailable (${response.status})`)
  return validateReplay(await response.json())
}
