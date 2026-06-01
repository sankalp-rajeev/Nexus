import { useState } from 'react'
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react'
import type { EvalRun } from '../types'

function Delta({ value }: { value: number }) {
  if (value > 0.01)
    return (
      <span className="inline-flex items-center gap-0.5 font-mono text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-medium">
        <ArrowUpRight size={10} />+{value.toFixed(3)}
      </span>
    )
  if (value < -0.01)
    return (
      <span className="inline-flex items-center gap-0.5 font-mono text-xs px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 font-medium">
        <ArrowDownRight size={10} />{value.toFixed(3)}
      </span>
    )
  return (
    <span className="inline-flex items-center gap-0.5 font-mono text-xs px-2 py-0.5 rounded-full bg-stone-100 text-stone-500">
      <Minus size={10} />0.000
    </span>
  )
}

function Score({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-stone-300 font-mono text-xs">—</span>
  return <span className="font-mono text-xs text-stone-700 tabular-nums">{value.toFixed(3)}</span>
}

function fmtDate(ts: string) {
  try {
    return new Date(ts).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return ts }
}

type SortKey = 'score_delta' | 'created_at' | 'before_score' | 'after_score'

export default function PatchHistory({ runs }: { runs: EvalRun[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('score_delta')
  const [sortAsc, setSortAsc] = useState(false)

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const sorted = [...runs].sort((a, b) => {
    const av = a[sortKey] as number
    const bv = b[sortKey] as number
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return sortAsc ? av - bv : bv - av
  })

  function SortHeader({ label, k }: { label: string; k: SortKey }) {
    const active = sortKey === k
    return (
      <th
        className={`text-left py-2 pr-3 font-medium cursor-pointer select-none whitespace-nowrap hover:text-stone-700 transition-colors ${active ? 'text-stone-700' : 'text-stone-400'}`}
        onClick={() => toggleSort(k)}
      >
        {label}{active ? (sortAsc ? ' ↑' : ' ↓') : ''}
      </th>
    )
  }

  return (
    <section className="flex flex-col h-full">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-stone-800 tracking-tight">Patch History</h2>
        <p className="text-xs text-stone-400 font-mono mt-0.5">{runs.length} eval runs</p>
      </header>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs min-w-[640px]">
          <thead className="sticky top-0 bg-stone-50 z-10">
            <tr className="border-b border-stone-200">
              <SortHeader label="Time" k="created_at" />
              <th className="text-left py-2 pr-3 font-medium text-stone-400">Agent</th>
              <th className="text-left py-2 pr-3 font-medium text-stone-400">Failure</th>
              <th className="text-left py-2 pr-3 font-medium text-stone-400">Patch Type</th>
              <SortHeader label="Before" k="before_score" />
              <SortHeader label="After" k="after_score" />
              <SortHeader label="Delta" k="score_delta" />
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-12 text-center text-stone-300 font-mono text-xs">
                  No patches applied yet
                </td>
              </tr>
            ) : (
              sorted.map(run => (
                <tr key={run.run_id} className="border-b border-stone-100 hover:bg-stone-50/60 transition-colors">
                  <td className="py-2 pr-3 font-mono text-stone-400 whitespace-nowrap">{fmtDate(run.created_at)}</td>
                  <td className="py-2 pr-3 text-stone-700 font-medium truncate max-w-[7rem]">{run.agent_name}</td>
                  <td className="py-2 pr-3 font-mono text-stone-500">{run.failure_type ?? '—'}</td>
                  <td className="py-2 pr-3 font-mono text-stone-400 text-xs">{run.patch_type ?? '—'}</td>
                  <td className="py-2 pr-3"><Score value={run.before_score} /></td>
                  <td className="py-2 pr-3"><Score value={run.after_score} /></td>
                  <td className="py-2"><Delta value={run.score_delta} /></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
