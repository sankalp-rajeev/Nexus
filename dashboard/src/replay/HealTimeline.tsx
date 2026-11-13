import { STAGES, type ReplayHeal } from '../replay'
import { seconds } from './ui'

export type StepState = 'done' | 'pass' | 'fail' | 'skipped'

export interface Step { name: (typeof STAGES)[number]; state: StepState; line: string; time: string }

const STATE_STYLE: Record<StepState, string> = {
  done: 'border-sky-300 bg-sky-50 text-sky-900',
  pass: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  fail: 'border-rose-300 bg-rose-50 text-rose-900',
  skipped: 'border-stone-200 bg-stone-50 text-stone-500',
}
const STATE_WORD: Record<StepState, string> = { done: 'DONE', pass: 'PASS', fail: 'FAIL', skipped: 'SKIPPED' }

/** The six stages of one heal, derived only from the recorded fields. */
export function healSteps(heal: ReplayHeal): Step[] {
  const stages = heal.timing.stages_s
  const critic = heal.critic
  const verdict = heal.detector.verdict
  const detect: Step = {
    name: 'Detect', state: 'done', time: seconds(stages.detect),
    line: verdict === 'NORMAL' ? 'Verdict NORMAL: no failure flagged' : `Verdict ${verdict}${heal.detector.evidence ? `, evidence at step ${heal.detector.evidence.step}` : ''}`,
  }
  const propose: Step = critic.status === 'patch'
    ? { name: 'Propose', state: 'done', time: seconds(stages.critic_call), line: `${critic.patch_type} on ${critic.target_component}` }
    : critic.status === 'no_patch'
      ? { name: 'Propose', state: 'fail', time: seconds(stages.critic_call), line: 'No usable patch: failed validation or dry run' }
      : { name: 'Propose', state: 'skipped', time: seconds(stages.critic_call), line: 'No critic call: nothing to repair' }
  const checks = heal.gate.checks.map((check): Step => ({
    name: check.label as Step['name'], state: check.outcome, time: seconds(check.stage_seconds),
    line: check.outcome === 'skipped' ? 'Not run' : (check.detail ?? ''),
  }))
  const decision: Step = {
    name: 'Decision', state: heal.gate.decision === 'promoted' ? 'pass' : 'fail', time: '',
    line: heal.gate.decision === 'promoted' ? 'Promoted' : 'Rejected',
  }
  return [detect, propose, ...checks, decision]
}

export default function HealTimeline({ heal }: { heal: ReplayHeal }) {
  const steps = healSteps(heal)
  return (
    <ol className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-6 gap-2" aria-label={`Heal timeline for ${heal.heal_id}`}>
      {steps.map((step, index) => (
        <li key={step.name} data-step={step.name} data-state={step.state}
            className={`border rounded-lg p-3 text-xs min-w-0 ${STATE_STYLE[step.state]}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold">{index + 1}. {step.name}</span>
            <span className="font-mono">{STATE_WORD[step.state]}</span>
          </div>
          <p className="mt-1.5 leading-snug break-words">{step.line}</p>
          {step.time && <p className="mt-1 font-mono opacity-70">{step.time}</p>}
        </li>
      ))}
    </ol>
  )
}
