import type { CriticBlock } from '../replay'
import { Mono } from './ui'

export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="text-xs font-mono bg-paper border border-rule rounded p-2 overflow-auto max-h-80 whitespace-pre-wrap break-words" aria-label="Patch diff">
      {diff.split('\n').map((line, index) => {
        const cls = line.startsWith('+++') || line.startsWith('---') ? 'text-muted'
          : line.startsWith('+') ? 'bg-oksoft text-ok'
            : line.startsWith('-') ? 'bg-badsoft text-bad'
              : line.startsWith('@@') ? 'text-cool' : 'text-ink2'
        return <span key={index} className={`block px-2 py-1 ${cls}`}>{line || ' '}</span>
      })}
    </pre>
  )
}

/** The critic's recorded proposal: diagnosis, target, the patch itself, and what it cost. */
export default function CriticPatch({ critic }: { critic: CriticBlock }) {
  if (critic.status === 'not_called') {
    return <p className="text-sm text-ink2">The critic was not called. Reason recorded: {critic.reason}.</p>
  }
  return (
    <div className="space-y-3 text-sm">
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
        <dt className="text-muted">Critic</dt><dd>{critic.provider} · <Mono>{critic.model}</Mono> · prompt {critic.prompt_version}</dd>
        <dt className="text-muted">Patch</dt><dd><Mono>{critic.patch_type}</Mono> on <Mono>{critic.target_component}</Mono></dd>
        <dt className="text-muted">Confidence</dt><dd>{critic.confidence}</dd>
        <dt className="text-muted">Cited span</dt><dd><Mono>{critic.cited_span_id}</Mono> (step {critic.cited_step})</dd>
        <dt className="text-muted">Dry run</dt><dd>{critic.dry_run_applied ? 'applied cleanly' : 'failed'}</dd>
        <dt className="text-muted">Call</dt>
        <dd className="font-mono">{critic.usage?.input_tokens} in / {critic.usage?.output_tokens} out tokens, {critic.usage?.latency_ms ? `${(critic.usage.latency_ms / 1000).toFixed(1)} s` : 'n/a'}{critic.usage?.cost_usd != null ? `, $${critic.usage.cost_usd.toFixed(6)}` : ''}</dd>
      </dl>
      {critic.explanation && <div><p className="text-xs font-medium text-muted">Explanation</p><p className="text-xs text-ink leading-relaxed mt-1 whitespace-pre-wrap">{critic.explanation}</p></div>}
      {critic.root_cause_analysis && (
        <details><summary className="text-xs font-medium text-muted cursor-pointer">Root cause analysis</summary>
          <p className="text-xs text-ink leading-relaxed mt-1 whitespace-pre-wrap">{critic.root_cause_analysis}</p></details>
      )}
      {critic.diff
        ? <div><p className="text-xs font-medium text-muted mb-1">Change to the agent&apos;s system prompt</p><DiffView diff={critic.diff} /></div>
        : critic.patch_content && (
          <div>
            <p className="text-xs font-medium text-muted mb-1">Patch content for <Mono>{critic.target_component}</Mono></p>
            <pre className="text-xs font-mono bg-paper3 p-2 rounded overflow-auto max-h-64 whitespace-pre-wrap break-words">{critic.patch_content}</pre>
          </div>
        )}
      {critic.diff && critic.patch_content && (
        <details><summary className="text-xs font-medium text-muted cursor-pointer">Full patched prompt</summary>
          <pre className="text-xs font-mono bg-paper3 p-2 rounded overflow-auto max-h-64 whitespace-pre-wrap break-words mt-1">{critic.patch_content}</pre></details>
      )}
      {critic.estimated_impact && <p className="text-xs text-muted">Estimated impact (the critic&apos;s claim, not a measurement): {critic.estimated_impact}</p>}
      {critic.critic_notes && critic.critic_notes.length > 0 && (
        <div><p className="text-xs font-medium text-muted">Recorded validation notes</p>
          <ul className="list-disc ml-5 text-xs text-ink2">{critic.critic_notes.map(note => <li key={note}>{note}</li>)}</ul></div>
      )}
    </div>
  )
}
