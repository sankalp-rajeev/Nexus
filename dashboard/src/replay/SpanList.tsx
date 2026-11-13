import type { ReplaySpan } from '../replay'

const TYPE_STYLE: Record<string, string> = {
  llm_call: 'text-violet-700 bg-violet-50',
  tool_call: 'text-sky-700 bg-sky-50',
  agent_step: 'text-amber-700 bg-amber-50',
  memory_read: 'text-teal-700 bg-teal-50',
  retrieval: 'text-teal-700 bg-teal-50',
}

function Text({ label, text, chars }: { label: string; text?: string; chars?: number }) {
  if (!text) return null
  return (
    <div>
      <p className="text-xs font-medium text-stone-500">{label}</p>
      <pre className="mt-1 p-2 bg-stone-100 text-xs font-mono whitespace-pre-wrap break-words max-h-64 overflow-auto rounded">{text}</pre>
      {chars ? <p className="text-xs text-stone-400 mt-1">Showing the first {text.length.toLocaleString()} of {chars.toLocaleString()} characters.</p> : null}
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
              className={`border rounded-lg bg-white ${evidence ? 'border-amber-400 ring-1 ring-amber-300' : cited ? 'border-sky-300' : 'border-stone-200'}`}>
            <details>
              <summary className="cursor-pointer list-none px-3 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="font-mono text-stone-400 w-6 tabular-nums">{index}</span>
                <span className={`font-mono px-2 py-0.5 rounded font-medium ${TYPE_STYLE[span.span_type] ?? 'text-stone-600 bg-stone-100'}`}>{span.span_type}</span>
                {typeof span.metadata?.tool_name === 'string' && <span className="font-mono text-stone-600">{span.metadata.tool_name}</span>}
                {span.duration_ms != null && <span className="font-mono text-stone-400 tabular-nums">{span.duration_ms.toFixed(1)} ms</span>}
                {span.error_type
                  ? <span className="font-mono px-2 py-0.5 rounded bg-rose-50 text-rose-700">{span.error_type}</span>
                  : <span className="font-mono px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">no span error</span>}
                {evidence && <span className="font-semibold text-amber-700">detector evidence</span>}
                {cited && <span className="font-semibold text-sky-700">cited by the critic</span>}
                <span className="font-mono text-stone-300 break-all">{span.span_id}</span>
              </summary>
              <div className="px-3 pb-3 space-y-2 border-t border-stone-100 pt-2">
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
