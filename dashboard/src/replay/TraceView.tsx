import { useState } from 'react'
import type { ReplayData } from '../replay'
import DetectorPanel from './DetectorPanel'
import SpanList from './SpanList'
import { FailureChip, Section } from './ui'

export default function TraceView({ data }: { data: ReplayData }) {
  const ruleSelected = new Set(data.provenance.selected_trace_ids_by_rule)
  const ordered = [...data.traces].sort((a, b) => Number(ruleSelected.has(b.trace_id)) - Number(ruleSelected.has(a.trace_id)) || a.trace_id.localeCompare(b.trace_id))
  const [selected, setSelected] = useState(ordered[0]?.trace_id ?? '')
  const trace = data.traces.find(item => item.trace_id === selected)
  return (
    <div className="space-y-4">
      <label className="block text-sm">
        Trace ({data.traces.length} DEV traces: {ruleSelected.size} chosen by the class rule, the rest belong to the heals)
        <select value={selected} onChange={event => setSelected(event.target.value)}
                className="block mt-2 border border-stone-300 bg-white p-2 max-w-full w-full sm:w-auto text-sm">
          {ordered.map(item => (
            <option key={item.trace_id} value={item.trace_id}>
              {item.trace_id} · {item.detector.verdict} (label {item.detector.dev_label}){ruleSelected.has(item.trace_id) ? '' : ' · heal'}
            </option>
          ))}
        </select>
      </label>
      {trace && (
        <div className="space-y-4" data-trace={trace.trace_id}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs">{trace.trace_id}</span>
            <FailureChip name={trace.detector.verdict} />
            <span className="text-xs text-stone-500">task {trace.task_id} · {trace.family} · {trace.spans.length} spans</span>
          </div>
          <Section title="Detector verdict and evidence"><DetectorPanel detector={trace.detector} /></Section>
          <Section title="Recorded run" hint="The detector view of the trace.">
            <p className="text-sm whitespace-pre-wrap break-words">{trace.root_input}</p>
            <details><summary className="text-xs font-medium text-stone-500 cursor-pointer">Recorded final output</summary>
              <p className="text-sm mt-1 whitespace-pre-wrap break-words">{trace.final_output ?? 'No final output recorded.'}</p></details>
            <SpanList spans={trace.spans} evidenceSpanId={trace.detector.evidence?.span_id} />
          </Section>
        </div>
      )}
    </div>
  )
}
