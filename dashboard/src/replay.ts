import type { Alert, PatchProposal, Span } from './types'

export interface ReplayTrace {
  trace_id: string
  agent_name: string
  root_input: string
  final_output: string | null
  spans: Span[]
}

export interface ReplayData {
  schema_version: 1
  mode: 'replay'
  split: 'dev'
  read_only: true
  notices: string[]
  provenance: { source_blobs: Record<string, string> }
  traces: ReplayTrace[]
  alerts: Alert[]
  proposals: PatchProposal[]
  gate_decisions: { trace_id: string; status: 'placeholder'; decision: null; reason: string }[]
}

export async function loadReplay(): Promise<ReplayData> {
  const response = await fetch(`${import.meta.env.BASE_URL}replay.json`)
  if (!response.ok) throw new Error(`Replay export unavailable (${response.status})`)
  const data = await response.json()
  if (data.schema_version !== 1 || data.mode !== 'replay' || data.split !== 'dev' || data.read_only !== true ||
      !['traces', 'alerts', 'proposals', 'gate_decisions', 'notices'].every(key => Array.isArray(data[key]))) {
    throw new Error('Unsupported replay export: expected read-only DEV schema version 1')
  }
  return data as ReplayData
}
