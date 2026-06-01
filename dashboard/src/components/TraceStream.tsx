import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import type { Span } from '../types'

const SPAN_TYPE_COLOR: Record<string, string> = {
  llm_call: 'text-violet-700 bg-violet-50',
  tool_call: 'text-sky-700 bg-sky-50',
  agent_step: 'text-amber-700 bg-amber-50',
  retrieval: 'text-teal-700 bg-teal-50',
}

function statusBadge(span: Span) {
  if (span.error_type) {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded bg-rose-50 text-rose-700 font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500 inline-block" />
        {span.error_type}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-medium">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
      NORMAL
    </span>
  )
}

function spanTypePill(type: string) {
  const cls = SPAN_TYPE_COLOR[type] ?? 'text-stone-600 bg-stone-100'
  return (
    <span className={`font-mono text-xs px-2 py-0.5 rounded font-medium ${cls}`}>
      {type}
    </span>
  )
}

function fmtTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}

export default function TraceStream({ spans }: { spans: Span[] }) {
  const [paused, setPaused] = useState(false)
  const [displayed, setDisplayed] = useState<Span[]>([])
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!paused) {
      setDisplayed(spans.slice(0, 50))
    }
  }, [spans, paused])

  useEffect(() => {
    if (!paused && containerRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [displayed, paused])

  return (
    <section className="flex flex-col h-full">
      <header className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-stone-800 tracking-tight">Live Trace Stream</h2>
          <p className="text-xs text-stone-400 font-mono mt-0.5">
            {displayed.length} spans &bull; last 50
          </p>
        </div>
        <button
          onClick={() => setPaused(p => !p)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-stone-200 text-stone-600 hover:border-stone-300 hover:text-stone-800 transition-colors"
        >
          {paused ? <Play size={12} /> : <Pause size={12} />}
          {paused ? 'Resume' : 'Pause'}
        </button>
      </header>

      <div ref={containerRef} className="flex-1 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-stone-50 z-10">
            <tr className="border-b border-stone-200">
              <th className="text-left py-2 pr-3 font-mono text-stone-400 font-medium w-20">Time</th>
              <th className="text-left py-2 pr-3 font-medium text-stone-500 w-32">Agent</th>
              <th className="text-left py-2 pr-3 font-medium text-stone-500 w-28">Type</th>
              <th className="text-right py-2 pr-3 font-mono text-stone-400 font-medium w-20">ms</th>
              <th className="text-left py-2 font-medium text-stone-500">Status</th>
            </tr>
          </thead>
          <tbody>
            {displayed.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-12 text-center text-stone-300 font-mono text-xs">
                  Waiting for spans...
                </td>
              </tr>
            ) : (
              displayed.map((span) => (
                <tr
                  key={span.span_id}
                  className="border-b border-stone-100 hover:bg-stone-50/60 transition-colors group"
                >
                  <td className="py-2 pr-3 font-mono text-stone-400 tabular-nums whitespace-nowrap">
                    {fmtTime(span.server_timestamp)}
                  </td>
                  <td className="py-2 pr-3 text-stone-700 font-medium truncate max-w-[8rem]" title={span.agent_name}>
                    {span.agent_name}
                  </td>
                  <td className="py-2 pr-3">{spanTypePill(span.span_type)}</td>
                  <td className="py-2 pr-3 font-mono text-stone-500 text-right tabular-nums">
                    {span.duration_ms != null ? span.duration_ms.toFixed(0) : '—'}
                  </td>
                  <td className="py-2">{statusBadge(span)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
