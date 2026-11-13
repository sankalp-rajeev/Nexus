import type { ReactNode } from 'react'
import type { Outcome } from '../replay'

export const FAILURE_STYLE: Record<string, string> = {
  HALLUCINATION: 'text-cool bg-coolsoft border-rule',
  TOOL_MISFIRE: 'text-cool bg-coolsoft border-rule',
  LOOP_DETECTED: 'text-bad bg-badsoft border-bad',
  PLAN_DRIFT: 'text-cool bg-coolsoft border-cool',
  CONTEXT_BLEED: 'text-cool bg-coolsoft border-rule',
  NORMAL: 'text-ok bg-oksoft border-ok',
  OTHER_FAILURE: 'text-ink2 bg-paper3 border-rule',
}

const OUTCOME_STYLE: Record<string, string> = {
  pass: 'text-ok bg-oksoft border-ok',
  fail: 'text-bad bg-badsoft border-bad',
  skipped: 'text-muted bg-paper3 border-rule',
  promoted: 'text-ok bg-oksoft border-ok',
  rejected: 'text-bad bg-badsoft border-bad',
}

export function FailureChip({ name }: { name: string }) {
  return (
    <span className={`inline-block font-mono text-xs px-2 py-0.5 rounded border ${FAILURE_STYLE[name] ?? 'text-ink2 bg-paper3 border-rule'}`}>
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
    <section className="border border-rule bg-paper2 rounded-lg p-4 space-y-3 min-w-0">
      <header>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint && <p className="text-xs text-muted mt-0.5">{hint}</p>}
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
