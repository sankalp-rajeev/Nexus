import type { ReplayData, ReplayHeal } from '../replay'
import CriticPatch from './CriticPatch'
import DetectorPanel from './DetectorPanel'
import HealTimeline from './HealTimeline'
import SpanList from './SpanList'
import { FailureChip, Mono, OutcomeBadge, Section, seconds } from './ui'

export function HealPicker({ heals, selected, onSelect }: { heals: ReplayHeal[]; selected: string; onSelect: (id: string) => void }) {
  return (
    <div role="tablist" aria-label="Recorded heals" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
      {heals.map(heal => (
        <button key={`${heal.run}-${heal.heal_id}`} role="tab" aria-selected={selected === `${heal.run}-${heal.heal_id}`}
                onClick={() => onSelect(`${heal.run}-${heal.heal_id}`)}
                className={`text-left border rounded-lg p-3 transition-colors ${selected === `${heal.run}-${heal.heal_id}` ? 'border-stone-800 bg-white shadow-sm' : 'border-stone-200 bg-stone-50 hover:bg-white'}`}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-medium">{heal.heal_id}{heal.run === 'gemini' ? ' · side row' : ''}</span>
            <FailureChip name={heal.detector.verdict === 'NORMAL' ? 'NORMAL' : heal.detector_failure_class} />
            <OutcomeBadge value={heal.gate.decision} />
          </div>
          <p className="text-xs text-stone-600 mt-1.5 leading-snug">{heal.selected_because.split('matching: ')[1]}</p>
        </button>
      ))}
    </div>
  )
}

export default function HealView({ data, heal }: { data: ReplayData; heal: ReplayHeal }) {
  const trace = data.traces.find(item => item.trace_id === heal.trace_id)
  if (!trace) return <p role="alert">Trace {heal.trace_id} is missing from the export.</p>
  return (
    <div className="space-y-4" data-heal={heal.heal_id}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-base font-semibold">{heal.heal_id} · task <Mono>{heal.task_id}</Mono></h2>
        <FailureChip name={heal.detector.verdict} />
        <OutcomeBadge value={heal.gate.decision} />
        <span className="text-xs text-stone-500">{heal.run_label}</span>
      </header>
      <p className="text-xs text-stone-500">Selected by rule: {heal.selected_because}.</p>
      <HealTimeline heal={heal} />
      <div className="border border-stone-200 bg-white rounded-lg p-4 text-sm" aria-label="Decision">
        <span className="font-semibold">Decision: </span>{heal.gate.reason}
        <span className="text-xs text-stone-500"> Total {seconds(heal.timing.total_s)}, provider cost ${heal.cost.provider_usd?.toFixed(4) ?? 'n/a'}.</span>
        {heal.paired_headline_run && (
          <p className="text-xs text-stone-500 mt-1">
            The same occurrence in the 100-heal run (DeepSeek critic) was {heal.paired_headline_run.decision} ({heal.paired_headline_run.source}).
          </p>
        )}
      </div>
      <div className="grid xl:grid-cols-2 gap-4">
        <Section title="Detector verdict and evidence" hint="Recorded scored-detector prediction for this DEV trace.">
          <DetectorPanel detector={heal.detector} />
        </Section>
        <Section title="Critic's patch" hint="The recorded proposal, as the critic returned it.">
          <CriticPatch critic={heal.critic} />
        </Section>
      </div>
      <Section title="Gate checks" hint="Each check is a deterministic pass/fail over re-runs; no model judges the patch.">
        <ul className="divide-y divide-stone-100">
          {heal.gate.checks.map(check => (
            <li key={check.id} className="py-2 grid sm:grid-cols-[10rem_6rem_1fr] gap-x-4 gap-y-1 text-sm" data-check={check.id} data-outcome={check.outcome}>
              <span className="font-medium">{check.label}</span>
              <span><OutcomeBadge value={check.outcome} /></span>
              <span className="text-xs text-stone-600 min-w-0">
                <span className="block text-stone-500">{check.rule}</span>
                <span className="block mt-0.5">{check.outcome === 'skipped' ? 'Not run: the heal ended before this check.' : check.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="The trace" hint={`${trace.agent_name} · ${trace.spans.length} spans · the detector view: what the detectors and the critic were given.`}>
        <div className="space-y-3">
          <div><p className="text-xs font-medium text-stone-500">Task input</p>
            <p className="text-sm whitespace-pre-wrap break-words">{trace.root_input}</p></div>
          <details><summary className="text-xs font-medium text-stone-500 cursor-pointer">Recorded final output</summary>
            <p className="text-sm mt-1 whitespace-pre-wrap break-words">{trace.final_output ?? 'No final output recorded.'}</p></details>
          <SpanList spans={trace.spans} evidenceSpanId={trace.detector.evidence?.span_id} citedSpanId={heal.critic.cited_span_id} />
        </div>
      </Section>
      <details className="text-xs text-stone-500">
        <summary className="cursor-pointer">Where this heal comes from</summary>
        <dl className="mt-2 grid sm:grid-cols-[9rem_1fr] gap-x-4 gap-y-1">
          <dt>Run</dt><dd>{heal.source.run}</dd>
          <dt>Record</dt><dd><Mono>{heal.source.record}</Mono> in the Phase 5 run directory (not copied into this repository)</dd>
          <dt>Record SHA-256</dt><dd><Mono>{heal.source.record_sha256}</Mono></dd>
          <dt>Executed at commit</dt><dd><Mono>{heal.source.execution_commit}</Mono>, frozen reference {heal.source.frozen_reference}</dd>
        </dl>
      </details>
    </div>
  )
}
