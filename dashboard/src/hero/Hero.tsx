import { Component, type ReactNode } from 'react'
import '@fontsource/host-grotesk/latin-400.css'
import '@fontsource/host-grotesk/latin-500.css'
import '@fontsource/atkinson-hyperlegible-mono/latin-400.css'
import '@fontsource/atkinson-hyperlegible-mono/latin-500.css'
import './hero.css'
import type { ReplayData } from '../replay'
import { capitalise, decimal, interval, oneIn, proof, word } from './numbers'
import { CopyBlock, DefinitionLink, Fraction, SourceLink } from './parts'

export const INSTALL = 'pip install nexus-llmops'

export function Nav() {
  return (
    <header className="nx-nav">
      <div className="container nx-nav__row">
        <p className="nx-nav__brand">
          <a className="nx-wordmark" href="#top" aria-label="Nexus, back to the top">Nexus</a>
          <span className="nx-nav__tagline">Open-source reliability layer for LLM agents.</span>
        </p>
        <nav aria-label="Page">
          <ul className="nx-nav__links">
            <li><a href="#how">How it works</a></li>
            <li><a href="#use">Use it</a></li>
            <li><a href="#evidence">Evidence</a></li>
          </ul>
        </nav>
      </div>
    </header>
  )
}

/** A missing or malformed number hides its section, never the rest of the page. */
export class SectionBoundary extends Component<{ children: ReactNode; name: string }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    return (
      <section className="nx-section nx-section--failed" role="alert">
        <div className="container">
          <p>The {this.props.name} numbers are missing from replay.json. Re-export it with dashboard/scripts/export_replay.py. The rest of the page still works.</p>
        </div>
      </section>
    )
  }
}

export default function Hero({ data }: { data: ReplayData }) {
  const broke = proof(data, 'llm_patches_broke', 'fraction')
  const genuine = proof(data, 'genuine_patches_broke', 'fraction')
  const falsePromotions = proof(data, 'old_rule_false_promotions', 'fraction')
  const freshSeeds = proof(data, 'fresh_seed_failures', 'fraction')
  const recall = proof(data, 'detection_recall', 'comparison')
  const allTest = [broke, falsePromotions, freshSeeds, recall].every(item => item.split === 'test')

  return (
    <section className="nx-hero" aria-labelledby="hero-head">
      <div className="container nx-hero__grid">
        <div className="nx-hero__text">
          <h1 id="hero-head">
            <span className="nx-hero__setup">LLM agents can propose their own fixes.</span>{' '}
            <span className="nx-hero__finding">
              {capitalise(oneIn(broke.k, broke.n))} LLM‑written patches broke a task that was already passing.
            </span>
          </h1>
          <p className="lead nx-hero__lead">
            Nexus detects failures live and lets an LLM propose a fix. A fix is promoted only after a
            three-check verification job (repair, held-out, regression) passes against your agent’s task
            suite; the results below come from that job on NexusBench.
          </p>
          <div className="nx-actions">
            <CopyBlock text={INSTALL} label="the install command" />
            <div className="nx-actions__row">
              <a className="btn btn--quiet nx-actions__evidence" href="#finding">See the evidence</a>
              <a className="nx-link" href={data.provenance.repository}>GitHub</a>
            </div>
          </div>
        </div>

        <figure className="nx-proof" aria-labelledby="nx-proof-caption">
          <figcaption id="nx-proof-caption" className="nx-proof__head">
            {allTest ? 'Held-out test set, scored once' : 'Development and test numbers'}
          </figcaption>
          <div className="nx-proof__lead">
            <p className="nx-reading nx-reading--lead"><Fraction k={broke.k} n={broke.n} /></p>
            <p className="nx-proof__label">LLM-written patches broke at least one task that was already passing</p>
            <div className="nx-bar" aria-hidden="true">
              <span className="nx-bar__broke" style={{ flexGrow: broke.k }} />
              <span className="nx-bar__held" style={{ flexGrow: broke.n - broke.k }} />
            </div>
            <p className="nx-proof__aside">
              {genuine.k} of {genuine.n} when you exclude simple reverts of the injected fault
            </p>
            <div className="nx-proof__meta">
              {broke.wilson95 && <span className="nx-measured">95% CI {interval(broke.wilson95)}</span>}
              <SourceLink data={data} item={broke} />
            </div>
          </div>

          <div className="nx-proof__cell">
            <p className="nx-reading"><Fraction k={falsePromotions.k} n={falsePromotions.n} /></p>
            <div className="nx-proof__body">
              <p className="nx-proof__label">
                patches the usual “rerun improved” rule would promote improved their own task but failed the held-out or regression check
              </p>
              <p className="nx-proof__links">
                <SourceLink data={data} item={falsePromotions} />
                {falsePromotions.definition && <DefinitionLink data={data} at={falsePromotions.definition} />}
              </p>
            </div>
          </div>

          <div className="nx-proof__cell">
            <p className="nx-reading"><Fraction k={freshSeeds.k} n={freshSeeds.n} /></p>
            <div className="nx-proof__body">
              <p className="nx-proof__label">gate-promoted patches failed when rerun from scratch with new random seeds</p>
              <p className="nx-proof__links">
                <SourceLink data={data} item={freshSeeds} />
                {freshSeeds.definition && <DefinitionLink data={data} at={freshSeeds.definition} />}
              </p>
            </div>
          </div>

          <div className="nx-proof__cell">
            <p className="nx-reading">{decimal(recall.value)}</p>
            <div className="nx-proof__body">
              <p className="nx-proof__label">
                failure-detection macro recall over {word(recall.classes)} failure classes, vs <span className="nx-measured nx-measured--inline">{decimal(recall.baseline)}</span> for the old classifier
              </p>
              <SourceLink data={data} item={recall} />
            </div>
          </div>
        </figure>
      </div>
    </section>
  )
}
