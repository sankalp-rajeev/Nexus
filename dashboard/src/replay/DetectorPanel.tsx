import type { DetectorVerdict } from '../replay'
import { FailureChip, Mono } from './ui'

export default function DetectorPanel({ detector }: { detector: DetectorVerdict }) {
  const agreement = detector.agrees_with_dev_label
  const threshold = detector.threshold as { detector?: string; threshold?: number } | null
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-xs text-muted">Detector verdict</span>
        <FailureChip name={detector.verdict} />
        <span className="text-xs text-muted">DEV label</span>
        <FailureChip name={detector.dev_label} />
        <span className={`text-xs font-medium ${agreement === null ? 'text-muted' : agreement ? 'text-ok' : 'text-bad'}`}>
          {agreement === null ? 'outside the five detector classes: not scored' : agreement ? 'agrees with the label' : 'disagrees with the label'}
        </span>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
        {threshold?.detector && (<><dt className="text-muted">Detector</dt><dd>{threshold.detector}</dd></>)}
        {detector.nli.ran && (<><dt className="text-muted">NLI score</dt>
          <dd className="font-mono">{detector.nli.score?.toFixed(4)} ({detector.nli.flag ? 'flagged' : 'not flagged'}{typeof threshold?.threshold === 'number' ? `, threshold ${threshold.threshold}` : ''})</dd></>)}
      </dl>
      {detector.evidence ? (
        <div>
          <p className="text-xs font-medium text-muted">
            Evidence: span <Mono>{detector.evidence.span_id}</Mono>, step {detector.evidence.step}
          </p>
          <pre className="mt-1 p-2 bg-paper3 text-xs font-mono whitespace-pre-wrap break-words max-h-48 overflow-auto rounded">{detector.evidence.text}</pre>
          {detector.evidence.text_chars ? <p className="text-xs text-muted mt-1">Showing the first {detector.evidence.text.length} of {detector.evidence.text_chars.toLocaleString()} characters.</p> : null}
          <p className="text-xs text-muted mt-1">The location is a deterministic heuristic over the verdict, not a detector attribution.</p>
        </div>
      ) : <p className="text-xs text-muted">No evidence: the detectors flagged nothing on this trace.</p>}
    </div>
  )
}
