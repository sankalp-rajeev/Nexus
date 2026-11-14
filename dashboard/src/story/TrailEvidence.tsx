import { sourceUrl, type ReplayData, type TrailMetric } from '../replay'

function proportion(metric: TrailMetric): string {
  if (metric.estimate === null || !metric.wilson95) return 'undefined'
  const [low, high] = metric.wilson95
  return `${metric.numerator}/${metric.denominator} [${(100 * low).toFixed(2)}%, ${(100 * high).toFixed(2)}%]`
}

export default function TrailEvidence({ data }: { data: ReplayData }) {
  const trail = data.external_trail
  if (!trail) return <p>The external aggregate evidence is unavailable in this export.</p>
  const row = (version: 'v1' | 'v2', cls: string, cohort = 'TRAIL-B') => {
    const found = trail.rows.find(r => r.cohort === cohort && r.version === version && r.class_name === cls && r.mapping === 'primary')
    if (!found) throw new Error('External aggregate row is missing')
    return found
  }
  const link = (path: string, text: string) => <a className="nx-source" href={sourceUrl(data, path)} target="_blank" rel="noreferrer">{text}</a>
  const oldLoop = row('v1', 'LOOP_DETECTED'), loop = row('v2', 'LOOP_DETECTED')
  const oldMisfire = row('v1', 'TOOL_MISFIRE'), misfire = row('v2', 'TOOL_MISFIRE')
  const oldHall = row('v1', 'HALLUCINATION'), hall = row('v2', 'HALLUCINATION')
  const aLoop = row('v1', 'LOOP_DETECTED', 'TRAIL-A'), aHall = row('v1', 'HALLUCINATION', 'TRAIL-A')
  const g = trail.guardrail
  const abstentions = (values: Record<string, number>) => Object.values(values).reduce((a, b) => a + b, 0)
  return (
    <section className="nx-external" aria-labelledby="external-trail-head" id="external-trail">
      <h3 id="external-trail-head">External check (TRAIL)</h3>
      <p>TRAIL contains <span className="nx-measured">{trail.dataset.traces}</span> human-labelled real agent traces.
        {' '}{trail.dataset.license}-licensed and gated; no TRAIL content is redistributed here.{' '}
        <a className="nx-source" href={trail.dataset.card} target="_blank" rel="noreferrer">Dataset card</a>{' '}
        {link(trail.sources.development, 'Dataset metadata')}</p>
      <p>Pre-registered: score frozen v1 once on A, diagnose on development data, freeze v2, then score both once on sealed B.
        {' '}Original mapping is primary; C3 is secondary with identical counts.{' '}{link(trail.sources.protocol, 'A3 protocol')}</p>
      <p>TRAIL-B: <span className="nx-measured">{loop.cohort_denominator}</span> traces. Intervals below are Wilson 95%.</p>
      <dl className="nx-rows nx-rows--limits">
        <div className="nx-rows__row">
          <dt>LOOP is primary.</dt>
          <dd><p>v1 recall <span className="nx-measured">{proportion(oldLoop.recall)}</span>; precision {proportion(oldLoop.precision)}.</p>
            <p>v2 recall <span className="nx-measured">{proportion(loop.recall)}</span>; precision <span className="nx-measured">{proportion(loop.precision)}</span>.</p>
            {link(loop.source, 'B LOOP counts and intervals')}</dd>
        </div>
        <div className="nx-rows__row">
          <dt>TOOL_MISFIRE is descriptive.</dt>
          <dd>v1: <span className="nx-measured">{oldMisfire.tp + oldMisfire.fp}</span> flags and <span className="nx-measured">{oldMisfire.gold_positive}</span> positives.
            {' '}v2: <span className="nx-measured">{misfire.tp + misfire.fp}</span> flags and <span className="nx-measured">{misfire.gold_positive}</span> positives.
            {' '}{misfire.gold_positive < trail.claims.misfire_min_positives ? 'Descriptive only; no claim.' : 'Counts alone do not establish a claim.'}
            {' '}{link(misfire.source, 'B MISFIRE counts')}</dd>
        </div>
        <div className="nx-rows__row">
          <dt>No hallucination improvement claim.</dt>
          <dd><p>v1 precision <span className="nx-measured">{proportion(oldHall.precision)}</span>; <span className="nx-measured">{abstentions(oldHall.abstentions)}</span> abstentions.</p>
            <p>v2 precision <span className="nx-measured">{proportion(hall.precision)}</span>; <span className="nx-measured">{abstentions(hall.abstentions)}</span> abstentions.</p>
            <p>Only <span className="nx-measured">{hall.evaluated}</span> traces are eligible. Abstentions are never negatives; final-answer claims need readable retrieved text.</p>
            {link(hall.source, 'B HALLUCINATION counts and eligibility')}</dd>
        </div>
      </dl>
      <p>Earlier v1 on A: LOOP recall <span className="nx-measured">{aLoop.recall.numerator}/{aLoop.recall.denominator}</span>;
        {' '}HALLUCINATION precision <span className="nx-measured">{aHall.precision.numerator}/{aHall.precision.denominator}</span>.
        {' '}A is context, not a paired comparison with B. {link(trail.sources.A, 'A aggregate')}</p>
      <p><strong>V2 is not live; v1 stays live.</strong> NexusBench DEV priority-label macro recall fell
        {' '}<span className="nx-measured">{g.priority_macro_v1.toFixed(3)} to {g.priority_macro_v2.toFixed(3)}</span>,
        {' '}a <span className="nx-measured">{g.priority_macro_drop.toFixed(4)}</span> drop beyond the <span className="nx-measured">{g.drop_limit.toFixed(2)}</span> guardrail,
        {' '}as LOOP masked <span className="nx-measured">{g.masked_misfires}</span> MISFIRE decisions.
        {' '}Together with B's MISFIRE false positives, this rules out v2 as a live-default candidate.{' '}{link(trail.sources.development, 'Development guardrail')}</p>
    </section>
  )
}
