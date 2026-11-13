import type { ReactNode } from 'react'
import type { Outcome } from '../replay'

export const FAILURE_STYLE: Record<string, string> = {
  HALLUCINATION: 'text-violet-700 bg-violet-50 border-violet-200',
  TOOL_MISFIRE: 'text-orange-700 bg-orange-50 border-orange-200',
  LOOP_DETECTED: 'text-red-700 bg-red-50 border-red-200',
  PLAN_DRIFT: 'text-sky-700 bg-sky-50 border-sky-200',
  CONTEXT_BLEED: 'text-teal-700 bg-teal-50 border-teal-200',
  NORMAL: 'text-emerald-700 bg-emerald-50 border-emerald-200',
  OTHER_FAILURE: 'text-stone-600 bg-stone-100 border-stone-200',
}

const OUTCOME_STYLE: Record<string, string> = {
  pass: 'text-emerald-800 bg-emerald-50 border-emerald-300',
  fail: 'text-rose-800 bg-rose-50 border-rose-300',
  skipped: 'text-stone-500 bg-stone-100 border-stone-200',
  promoted: 'text-emerald-800 bg-emerald-50 border-emerald-300',
  rejected: 'text-rose-800 bg-rose-50 border-rose-300',
}

export function FailureChip({ name }: { name: string }) {
  return (
    <span className={`inline-block font-mono text-xs px-2 py-0.5 rounded border ${FAILURE_STYLE[name] ?? 'text-stone-600 bg-stone-100 border-stone-200'}`}>
      {name}
    </span>
  )
}

export function OutcomeBadge({ value }: { value: Outcome | 'promoted' | 'rejected' }) {
  const word = value === 'pass' ? 'PASS' : value === 'fail' ? 'FAIL' : value === 'skipped' ? 'SKIPPED' : value.toUpperCase()
  return (
    <span className={`inline-block font-mono text-xs px-2 py-0.5 rounded border font-medium ${OUTCOME_STYLE[value]}`}>{word}</span>
  )
}

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="border border-stone-200 bg-white rounded-lg p-4 space-y-3 min-w-0">
      <header>
        <h3 className="text-sm font-semibold text-stone-800">{title}</h3>
        {hint && <p className="text-xs text-stone-500 mt-0.5">{hint}</p>}
      </header>
      {children}
    </section>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs break-all">{children}</span>
}

export function seconds(value: number | undefined | null): string {
  if (value === undefined || value === null) return 'n/a'
  return value < 1 ? `${(value * 1000).toFixed(0)} ms` : `${value.toFixed(1)} s`
}
