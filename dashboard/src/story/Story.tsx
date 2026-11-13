import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { Count, GateCheck, ReplayData, ReplayHeal, StoryFigure } from '../replay'
import {
  arm, decimal, figure, interval, proof, repoFile, secondsText, usd, value, word,
} from '../hero/numbers'
import { CopyBlock, Fraction, SourceLink } from '../hero/parts'
import { INSTALL } from '../hero/Hero'

// ── shared pieces ─────────────────────────────────────────────────────────────

function Section({ id, title, lead, children, band = false }: {
  id: string; title: string; lead?: ReactNode; children: ReactNode; band?: boolean
}) {
  return (
    <section id={id} className={`nx-section${band ? ' nx-section--band' : ''}`} aria-labelledby={`${id}-head`}>
      <div className="container">
        <div className="nx-section__head">
          <h2 id={`${id}-head`}>{title}</h2>
          {lead && <p className="lead nx-section__lead">{lead}</p>}
        </div>
        {children}
      </div>
    </section>
  )
}

function Ci({ count }: { count: Count }) {
  return count.wilson95 ? <span className="nx-measured">95% CI {interval(count.wilson95)}</span> : null
}

/** The recorded gate rules, read from a heal that ran all three checks. */
function gateRules(data: ReplayData): Record<GateCheck['id'], string> {
  const full = data.heals.find(heal => heal.gate.checks.every(check => check.outcome !== 'skipped'))
  const rules = { repair: '', heldout: '', regression: '' }
  for (const check of full?.gate.checks ?? []) rules[check.id] = check.rule
  return rules
}

// ── 2. the problem ────────────────────────────────────────────────────────────

export function Problem() {
  return (
    <Section id="problem" title="Rerunning the fix is the trap">
      <dl className="nx-rows">
        <div className="nx-rows__row">
          <dt>Agents fail quietly.</dt>
          <dd>A loop, a wrong tool call or an invented fact, and the run still returns an answer.</dd>
        </div>
        <div className="nx-rows__row">
          <dt>An LLM can propose the fix.</dt>
          <dd>It reads the trace, names a cause and rewrites the agent’s instructions.</dd>
        </div>
        <div className="nx-rows__row">
          <dt>The usual check is a trap.</dt>
          <dd>Rerun the failing task and ship if it improved. Nothing looks at the tasks that already worked.</dd>
        </div>
      </dl>
    </Section>
  )
}

// ── 3. what Nexus does ────────────────────────────────────────────────────────

export function Mechanism({ data }: { data: ReplayData }) {
  const rules = gateRules(data)
  const steps: { name: string; line: string; check?: boolean }[] = [
    { name: 'Detect', line: 'Detectors read each trace and flag the failure: a loop, a tool misfire, leaked context, a drifting plan or an invented fact.' },
    { name: 'Propose', line: 'An LLM critic reads the trace and writes a patch to the agent’s instructions.' },
    { name: 'Fix check', line: rules.repair, check: true },
    { name: 'Held-out check', line: `Held-out tasks are similar tasks the patch was not written for. ${rules.heldout}`, check: true },
    { name: 'Regression check', line: `Regression tasks are ones that already passed. ${rules.regression}`, check: true },
    { name: 'Promote or reject', line: 'A patch that passes all three checks is promoted. Anything else is rejected.' },
  ]
  return (
    <Section id="how" title="Three checks before a fix ships">
      <ol className="nx-flow" aria-label="The Nexus pipeline">
        {steps.map(step => (
          <li key={step.name} className={`nx-flow__step${step.check ? ' nx-flow__step--check' : ''}`}>
            <h3 className="nx-flow__name">{step.name}</h3>
            <p className="nx-flow__line">{step.line}</p>
          </li>
        ))}
      </ol>
    </Section>
  )
}

// ── 4. the finding ────────────────────────────────────────────────────────────

function FindingRow({ reading, label, children }: { reading: ReactNode; label: ReactNode; children: ReactNode }) {
  return (
    <div className="nx-index__row">
      <p className="nx-reading">{reading}</p>
      <p className="nx-index__label">{label}</p>
      <p className="nx-index__meta">{children}</p>
    </div>
  )
}

export function Finding({ data }: { data: ReplayData }) {
  const broke = proof(data, 'llm_patches_broke', 'fraction')
  const genuine = proof(data, 'genuine_patches_broke', 'fraction')
  const falsePromotions = proof(data, 'old_rule_false_promotions', 'fraction')
  const fresh = proof(data, 'fresh_seed_failures', 'fraction')
  const recall = proof(data, 'detection_recall', 'comparison')
  const repaired = figure(data, 'repaired_vs_no_patch')
  const critic = arm(repaired, 'critic')
  const noPatch = arm(repaired, 'no_patch')
  return (
    <Section id="finding" title="What the held‑out test set showed"
             lead="The test set is a separate set of tasks, locked away until the method was frozen, then scored once.">
      <div className="nx-index">
        <FindingRow reading={<Fraction k={broke.k} n={broke.n} />}
                    label={`LLM-written patches broke at least one task that already passed (${genuine.k} of ${genuine.n} that did more than undo the injected fault). Rerunning the failing task never shows this.`}>
          {broke.wilson95 && <Ci count={broke} />}<SourceLink data={data} item={broke} />
        </FindingRow>
        <FindingRow reading={<><Fraction k={critic.k} n={critic.n} /></>}
                    label={`patches that did more than undo the injected fault fixed their own task; a plain rerun with no patch fixed ${noPatch.k} of ${noPatch.n}.`}>
          <Ci count={critic} /><SourceLink data={data} item={repaired} />
        </FindingRow>
        <FindingRow reading={<Fraction k={falsePromotions.k} n={falsePromotions.n} />}
                    label="patches the “rerun improved” rule would ship were false promotions: they failed the held-out or regression check.">
          <Ci count={falsePromotions} /><SourceLink data={data} item={falsePromotions} />
        </FindingRow>
        <FindingRow reading={<Fraction k={fresh.k} n={fresh.n} />}
                    label="patches the gate promoted failed when rerun from scratch with new random seeds.">
          <Ci count={fresh} /><SourceLink data={data} item={fresh} />
        </FindingRow>
        <FindingRow reading={decimal(recall.value)}
                    label={`recall at spotting failures, averaged over ${word(recall.classes)} classes, vs ${decimal(recall.baseline)} for the old classifier.`}>
          <SourceLink data={data} item={recall} />
        </FindingRow>
      </div>
    </Section>
  )
}

// ── 4b. per class, and why the test set is scored once ───────────────────────

function Bar({ count, series, name }: { count: Count; series: 'a' | 'b'; name: string }) {
  const share = count.n ? count.k / count.n : 0
  const [low, high] = count.wilson95 ?? [share, share]
  return (
    <div className="nx-chart__bar">
      <span className="nx-chart__series">{name}</span>
      <span className="nx-chart__track" aria-hidden="true">
        <span className={`nx-chart__fill nx-chart__fill--${series}`} style={{ transform: `scaleX(${share})` }} />
        {count.wilson95 && (
          <span className="nx-chart__ci" style={{ left: `${low * 100}%`, right: `${100 - high * 100}%` }} />
        )}
      </span>
      <span className="nx-chart__value">
        <Fraction k={count.k} n={count.n} />
        {count.wilson95 && <span className="nx-chart__interval"> {interval(count.wilson95)}</span>}
      </span>
    </div>
  )
}

function ClassGroup({ data, item, name, note }: { data: ReplayData; item: StoryFigure; name: string; note: string }) {
  return (
    <div className="nx-chart__group">
      <h3 className="nx-chart__name">{name}</h3>
      <Bar count={arm(item, 'critic')} series="a" name="LLM critic" />
      <Bar count={arm(item, 'generic')} series="b" name="Generic template" />
      <p className="nx-chart__note">{note} <SourceLink data={data} item={item} /></p>
    </div>
  )
}

export function PerClass({ data }: { data: ReplayData }) {
  const loopTool = figure(data, 'loop_tool_misfire')
  const hallucination = figure(data, 'hallucination')
  const planDrift = figure(data, 'plan_drift')
  const regression = figure(data, 'regression_dev_test')
  const dev = arm(regression, 'dev')
  const test = arm(regression, 'test')
  return (
    <Section id="per-class" title="Where the critic earns its place" band
             lead="Share of test-set failures that ended with a promoted fix, by kind of failure.">
      <div className="nx-split">
        <figure className="nx-chart" aria-label="Promoted fixes per failure: LLM critic against a generic template">
          <ClassGroup data={data} item={loopTool} name="Loops and tool misfires"
                      note="The critic fixes what no template can." />
          <ClassGroup data={data} item={hallucination} name="Invented facts"
                      note="One plain rule does as well: undo the injected instruction." />
          <ClassGroup data={data} item={planDrift} name="Plan drift"
                      note="Unsolved by either." />
          <figcaption className="nx-chart__caption">
            Bars show the share promoted; the thin line is the 95% interval.
            {loopTool.interval_note ? ' The combined interval is computed from the summed counts.' : ''}
          </figcaption>
        </figure>
        <figure className="nx-chart nx-chart--single" aria-label="Patches that broke a passing task, development set against test set">
          <h3 className="nx-chart__name">Why the test set is scored once</h3>
          <Bar count={dev} series="a" name="Development set" />
          <Bar count={test} series="a" name="Test set" />
          <p className="nx-chart__note">
            Patches that broke a passing task rose from {dev.k} of {dev.n} where the critic was tuned to {test.k} of {test.n} on
            unseen tasks. A number measured where you tuned flatters you. <SourceLink data={data} item={regression} />
          </p>
        </figure>
      </div>
    </Section>
  )
}

// ── 5. walkthrough ────────────────────────────────────────────────────────────

const WALKTHROUGH = [
  { id: 'heal-043', tab: 'Blocked by the regression check' },
  { id: 'heal-010', tab: 'Blocked at the held-out check' },
  { id: 'heal-002', tab: 'Promoted' },
]

/** First sentence of a long recorded text, so the step reads at a glance; the rest sits behind a disclosure. */
function firstSentence(text: string | null | undefined): string {
  if (!text) return ''
  const match = text.match(/^.*?[.!?](\s|$)/)
  return (match ? match[0] : text).trim()
}

function evidenceSummary(heal: ReplayHeal): string {
  const raw = heal.detector.evidence?.text
  if (!raw) return ''
  try {
    const span = JSON.parse(raw) as Record<string, unknown>
    const parts = [span.error_type, span.error_message].filter(Boolean)
    return parts.length ? parts.join(': ') : String(span.output ?? '').slice(0, 160)
  } catch {
    return raw.slice(0, 160)
  }
}

/** The page's plain names for the recorded checks (the recorded label is kept in the replay explorer). */
const CHECK_NAME: Record<string, string> = { repair: 'Fix check', heldout: 'Held-out check', regression: 'Regression check' }

const OUTCOME_WORD = { pass: 'passed', fail: 'failed', skipped: 'not run' } as const

function HealStory({ heal }: { heal: ReplayHeal }) {
  const critic = heal.critic
  return (
    <ol className="nx-trail">
      <li className="nx-trail__step">
        <h3 className="nx-trail__name">Detect</h3>
        <p>The detector flagged <span className="nx-measured">{heal.detector.verdict}</span> at step {heal.detector.evidence?.step ?? 'n/a'} of task <span className="nx-measured">{heal.task_id}</span>.</p>
        {evidenceSummary(heal) && <p className="nx-trail__quote"><code>{evidenceSummary(heal)}</code></p>}
      </li>
      <li className="nx-trail__step">
        <h3 className="nx-trail__name">Propose</h3>
        {critic.status === 'patch' ? (
          <>
            <p className="nx-trail__said">The critic ({critic.provider}) wrote: “{firstSentence(critic.explanation)}”</p>
            <details className="nx-disclosure">
              <summary>The patch it proposed</summary>
              <pre className="nx-diff" tabIndex={0} aria-label="Patch as a diff against the agent's instructions"><code>{critic.diff ?? critic.patch_content}</code></pre>
              <p className="nx-trail__fine">The diff is derived from the recorded patch and the instructions it replaced.</p>
            </details>
          </>
        ) : <p>No usable patch: {critic.reason}</p>}
      </li>
      {heal.gate.checks.map(check => (
        <li key={check.id} className={`nx-trail__step nx-trail__step--${check.outcome}`}>
          <h3 className="nx-trail__name">
            {CHECK_NAME[check.id] ?? check.label} <span className={`nx-status nx-status--${check.outcome}`}>{OUTCOME_WORD[check.outcome]}</span>
          </h3>
          <p>{check.rule}</p>
          {check.detail && <p className="nx-trail__result"><span className="nx-measured">{check.detail}</span></p>}
        </li>
      ))}
      <li className={`nx-trail__step nx-trail__step--${heal.gate.decision === 'promoted' ? 'pass' : 'fail'}`}>
        <h3 className="nx-trail__name">
          Decision <span className={`nx-status nx-status--${heal.gate.decision === 'promoted' ? 'pass' : 'fail'}`}>{heal.gate.decision}</span>
        </h3>
        <p>{heal.gate.reason}</p>
        <p className="nx-trail__result"><span className="nx-measured">{secondsText(heal.timing.total_s)}</span> from alert to decision{heal.cost.provider_usd !== undefined && <>, <span className="nx-measured">{usd(heal.cost.provider_usd)}</span> in model calls</>}.</p>
      </li>
    </ol>
  )
}

export function Walkthrough({ data }: { data: ReplayData }) {
  const heals = WALKTHROUGH.map(item => ({ ...item, heal: data.heals.find(h => h.heal_id === item.id && h.run === 'main') }))
    .filter((item): item is typeof item & { heal: ReplayHeal } => Boolean(item.heal))
  const [active, setActive] = useState(0)
  const tabs = useRef<(HTMLButtonElement | null)[]>([])
  if (!heals.length) return null

  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = heals.length - 1
    const forward = event.key === 'ArrowDown' || event.key === 'ArrowRight'
    const back = event.key === 'ArrowUp' || event.key === 'ArrowLeft'
    const next = forward ? (index === last ? 0 : index + 1)
      : back ? (index === 0 ? last : index - 1)
        : event.key === 'Home' ? 0 : event.key === 'End' ? last : null
    if (next === null) return
    event.preventDefault()
    setActive(next)
    tabs.current[next]?.focus()
  }

  const current = heals[active]
  return (
    <Section id="walkthrough" title="One fix, step by step"
             lead="These walkthroughs are recorded runs on the development set; the headline numbers above are from the held-out test set.">
      <div className="nx-walk">
      <div className="nx-tabs" role="tablist" aria-label="Recorded heals" aria-orientation="vertical">
        {heals.map((item, index) => (
          <button key={item.id} type="button" role="tab" id={`tab-${item.id}`} aria-controls={index === active ? `panel-${item.id}` : undefined}
                  aria-selected={index === active} tabIndex={index === active ? 0 : -1}
                  ref={element => { tabs.current[index] = element }}
                  className="nx-tabs__tab" onClick={() => setActive(index)} onKeyDown={event => onKey(event, index)}>
            {item.tab}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${current.id}`} aria-labelledby={`tab-${current.id}`} className="nx-tabs__panel" tabIndex={0}>
        <p className="nx-tabs__id"><span className="nx-measured">{current.heal.heal_id}</span>, {current.heal.run_label}</p>
        <HealStory heal={current.heal} />
      </div>
      </div>
    </Section>
  )
}

// ── 6. how it works, speed and cost ───────────────────────────────────────────

const ARCHITECTURE = [
  { name: 'SDK or OpenTelemetry', line: 'Your agent emits spans.' },
  { name: 'Collector', line: 'Receives and validates them.' },
  { name: 'Kafka', line: 'Queues them in order.' },
  { name: 'Detectors', line: 'Classify each finished trace.' },
  { name: 'Critic', line: 'Proposes a patch.' },
  { name: 'Gate', line: 'Runs the three checks.' },
]

export function Architecture({ data }: { data: ReplayData }) {
  const alert = figure(data, 'time_to_alert')
  const decision = figure(data, 'time_to_verified_decision')
  const cost = figure(data, 'cost_per_fix')
  const sdk = figure(data, 'sdk_overhead')
  const ingest = figure(data, 'ingestion')
  return (
    <Section id="architecture" title="What runs, and what it costs" band
             lead="Measured on one laptop with the full stack running.">
      <ol className="nx-arch" aria-label="Architecture, in data-flow order">
        {ARCHITECTURE.map(part => (
          <li key={part.name} className="nx-arch__part">
            <span className="nx-arch__name">{part.name}</span>
            <span className="nx-arch__line">{part.line}</span>
          </li>
        ))}
      </ol>
      <dl className="nx-figures">
        <div className="nx-figures__item">
          <dt>Time to alert</dt>
          <dd className="nx-reading">{secondsText(value(alert, 'p50'))}</dd>
          <dd>median from an agent’s last span to an alert; {secondsText(value(alert, 'p95'))} at p95.</dd>
          <dd><SourceLink data={data} item={alert} /></dd>
        </div>
        <div className="nx-figures__item">
          <dt>Time to a checked decision</dt>
          <dd className="nx-reading">{secondsText(value(decision, 'p50'))}</dd>
          <dd>median for a heal that ran all three checks; the regression rerun takes most of it.</dd>
          <dd><SourceLink data={data} item={decision} /></dd>
        </div>
        <div className="nx-figures__item">
          <dt>Model cost per promoted fix</dt>
          <dd className="nx-reading">{usd(value(cost, 'per_promoted'))}</dd>
          <dd>all model calls in {value(cost, 'heals')} heals divided by the {value(cost, 'promoted')} that were promoted.</dd>
          <dd><SourceLink data={data} item={cost} /></dd>
        </div>
        <div className="nx-figures__item">
          <dt>SDK overhead per step</dt>
          <dd className="nx-reading">{decimal(value(sdk, 'p50'), 3)} ms</dd>
          <dd>median added to each agent step; {decimal(value(sdk, 'p99'), 3)} ms at p99.</dd>
          <dd><SourceLink data={data} item={sdk} /></dd>
        </div>
        <div className="nx-figures__item">
          <dt>Ingestion</dt>
          <dd className="nx-reading">{Math.round(value(ingest, 'sustained'))} events/s</dd>
          <dd>sustained on one laptop with every latency checkpoint met.</dd>
          <dd><SourceLink data={data} item={ingest} /></dd>
        </div>
      </dl>
    </Section>
  )
}

// ── 7. use it ─────────────────────────────────────────────────────────────────

const EXAMPLE = `import nexus_llmops as nexus

nexus.init(agent_name="my-pipeline", collector_url="http://localhost:8000")

@nexus.trace(span_type="tool_call")
def search(query: str) -> str:
    return "results for " + query

@nexus.trace(span_type="agent_step")
def run(task: str) -> str:
    return search(task)

run("find the order")
nexus.flush()`

const OTEL = `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8000/v1/traces
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`


export function UseIt({ data }: { data: ReplayData }) {
  const lite = figure(data, 'lite_limits')
  const clone = `git clone ${data.provenance.repository}.git
cd Nexus
docker compose -f docker-compose.lite.yml up -d --build`
  return (
    <Section id="use" title="Try it on your agent">
      <div className="nx-use">
        <div className="nx-use__item">
          <h3>Install</h3>
          <CopyBlock text={INSTALL} label="the install command" />
        </div>
        <div className="nx-use__item nx-use__item--wide">
          <h3>Trace an agent</h3>
          <CopyBlock text={EXAMPLE} label="the minimal example" multiline />
        </div>
        <div className="nx-use__item">
          <h3>Already on OpenTelemetry?</h3>
          <p>Point your OTLP exporter at the collector’s <code className="nx-inline-code">/v1/traces</code>. <a className="nx-link" href={repoFile(data, 'docs/otel_mapping.md')}>How spans map</a></p>
          <CopyBlock text={OTEL} label="the OpenTelemetry settings" multiline />
        </div>
        <div className="nx-use__item nx-use__item--full">
          <h3>Lite mode in Docker</h3>
          <p>One container on port 18000. It has no hallucination detector and no LLM critic. <SourceLink data={data} item={lite} label="Lite limits" /></p>
          <CopyBlock text={clone} label="the lite mode commands" multiline />
        </div>
      </div>
    </Section>
  )
}

// ── 8. honest limits ──────────────────────────────────────────────────────────

export function Limits({ data }: { data: ReplayData }) {
  const planDrift = arm(figure(data, 'plan_drift'), 'critic')
  const precision = figure(data, 'hallucination_precision')
  const alerts = figure(data, 'false_alerts')
  const v11 = figure(data, 'v11_registration')
  const temperature = figure(data, 'critic_temperature')
  const world = figure(data, 'invented_world')
  const lite = figure(data, 'lite_limits')
  return (
    <Section id="limits" title="What it does not do yet">
      <dl className="nx-rows nx-rows--limits">
        <div className="nx-rows__row">
          <dt>Plan drift is unsolved.</dt>
          <dd>The critic promoted {planDrift.k} of {planDrift.n} fixes. <SourceLink data={data} item={figure(data, 'plan_drift')} /></dd>
        </div>
        <div className="nx-rows__row">
          <dt>Two detection targets were missed.</dt>
          <dd>
            Of the traces flagged as invented facts, {decimal(value(precision, 'primary'), 2)} were right, against a {decimal(value(precision, 'target'), 2)} target.
            {' '}Normal traces drew {value(alerts, 'primary')} false alerts per 1,000, against a target of {value(alerts, 'target')}.
            {' '}A label correction registered before scoring gives {decimal(value(precision, 'v11'), 2)} and {value(alerts, 'v11')}.
            {' '}<SourceLink data={data} item={precision} /> <SourceLink data={data} item={alerts} /> <SourceLink data={data} item={v11} />
          </dd>
        </div>
        <div className="nx-rows__row">
          <dt>The benchmark world is invented.</dt>
          <dd>Its companies, orders and users are fictional. <SourceLink data={data} item={world} /></dd>
        </div>
        <div className="nx-rows__row">
          <dt>One laptop, one critic draw.</dt>
          <dd>Speed is from one machine. The critic runs at temperature {value(temperature, 'temperature')}, so a rerun can write a different patch. <SourceLink data={data} item={temperature} /></dd>
        </div>
        <div className="nx-rows__row">
          <dt>Lite mode is partial.</dt>
          <dd>No hallucination detector, no LLM critic, SQLite instead of Kafka. <SourceLink data={data} item={lite} /></dd>
        </div>
      </dl>
    </Section>
  )
}

// ── 9. evidence ───────────────────────────────────────────────────────────────

export function EvidenceIntro({ data, children }: { data: ReplayData; children: ReactNode }) {
  const numbers = data.headline.groups.reduce((total, group) => total + group.items.length, 0)
  return (
    <Section id="evidence" title="The recorded evidence"
             lead="Sealed means the test set stayed locked until the method was frozen, then was scored once. The replay below is development-set data.">
      <details className="nx-evidence">
        <summary className="nx-evidence__summary">
          Open the replay: {data.heals.length} recorded heals, {data.traces.length} traces, {numbers} headline numbers and their provenance
        </summary>
        <div className="nx-evidence__body">{children}</div>
      </details>
    </Section>
  )
}

// ── footer ────────────────────────────────────────────────────────────────────

export function Footer({ data }: { data: ReplayData }) {
  const repo = data.provenance.repository
  return (
    <footer className="nx-footer">
      <div className="container nx-footer__row">
        <p className="nx-footer__mark">Nexus</p>
        <ul className="nx-footer__links">
          <li><a href={repo}>GitHub</a></li>
          <li><a href="https://pypi.org/project/nexus-llmops/">PyPI</a></li>
          <li><a href={`${repo}/tree/main/docs`}>Docs</a></li>
          <li><a href={repoFile(data, 'RESULTS.md')}>RESULTS.md</a></li>
          <li><a href={repoFile(data, 'LICENSE')}>MIT license</a></li>
        </ul>
        <p className="nx-footer__note">Every number on this page is read from replay.json, exported from committed results at <span className="nx-measured">{data.provenance.generated_from_commit.slice(0, 7)}</span>.</p>
      </div>
    </footer>
  )
}
