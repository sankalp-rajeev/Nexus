import type { ReplaySpan } from '../replay'

const TYPE_STYLE: Record<string, string> = {
  llm_call: 'text-cool bg-coolsoft',
  tool_call: 'text-cool bg-coolsoft',
  agent_step: 'text-accent bg-accentsoft',
  memory_read: 'text-cool bg-coolsoft',
  retrieval: 'text-cool bg-coolsoft',
}

function Text({ label, text, chars }: { label: string; text?: string; chars?: number }) {
  if (!text) return null
  return (
    <div>
      <p className="text-xs font-medium text-muted">{label}</p>
      <pre className="mt-1 p-2 bg-paper3 text-xs font-mono whitespace-pre-wrap break-words max-h-64 overflow-auto rounded">{text}</pre>
      {chars ? <p className="text-xs text-muted mt-1">Showing the first {text.length.toLocaleString()} of {chars.toLocaleString()} characters.</p> : null}
    </div>
  )
}

/** One recorded span per row. The detector's evidence span and the span the critic cited are marked. */
export default function SpanList({ spans, evidenceSpanId, citedSpanId }: {
  spans: ReplaySpan[]; evidenceSpanId?: string | null; citedSpanId?: string | null
}) {
  return (
    <ol className="space-y-1.5" aria-label="Recorded spans">
      {spans.map((span, index) => {
        const evidence = span.span_id === evidenceSpanId
        const cited = span.span_id === citedSpanId
        return (
          <li key={span.span_id} data-span={span.span_id} data-evidence={evidence || undefined}
              className={`border rounded-lg bg-paper2 ${evidence ? 'border-accent ring-1 ring-accent' : cited ? 'border-cool' : 'border-rule'}`}>
            <details>
              <summary className="cursor-pointer list-none px-3 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="font-mono text-muted w-6 tabular-nums">{index}</span>
                <span className={`font-mono px-2 py-0.5 rounded font-medium ${TYPE_STYLE[span.span_type] ?? 'text-ink2 bg-paper3'}`}>{span.span_type}</span>
                {typeof span.metadata?.tool_name === 'string' && <span className="font-mono text-ink2">{span.metadata.tool_name}</span>}
                {span.duration_ms != null && <span className="font-mono text-muted tabular-nums">{span.duration_ms.toFixed(1)} ms</span>}
                {span.error_type
                  ? <span className="font-mono px-2 py-0.5 rounded bg-badsoft text-bad">{span.error_type}</span>
                  : <span className="font-mono px-2 py-0.5 rounded bg-oksoft text-ok">no span error</span>}
                {evidence && <span className="font-semibold text-accent">detector evidence</span>}
                {cited && <span className="font-semibold text-cool">cited by the critic</span>}
                <span className="font-mono text-muted break-all">{span.span_id}</span>
              </summary>
              <div className="px-3 pb-3 space-y-2 border-t border-rule pt-2">
                <Text label="Input" text={span.input} chars={span.input_chars} />
                <Text label="Output" text={span.output} chars={span.output_chars} />
                {span.error_message && <Text label="Error" text={span.error_message} />}
              </div>
            </details>
          </li>
        )
      })}
    </ol>
  )
}
