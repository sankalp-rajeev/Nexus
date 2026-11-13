import { useEffect, useState } from 'react'
import { loadReplay, type ReplayData } from './replay'
import HeadlinePanel from './replay/HeadlinePanel'
import HealView, { HealPicker } from './replay/HealView'
import ProvenancePanel from './replay/ProvenancePanel'
import TraceView from './replay/TraceView'
import './hero/hero.css'
import Hero, { Nav, SectionBoundary } from './hero/Hero'
import {
  Architecture, EvidenceIntro, Finding, Footer, Limits, Mechanism, PerClass, Problem, UseIt, Walkthrough,
} from './story/Story'

const TABS = [
  { id: 'heals', label: 'Heals' },
  { id: 'traces', label: 'Traces' },
  { id: 'numbers', label: 'Headline numbers' },
  { id: 'provenance', label: 'Provenance' },
] as const
type TabId = (typeof TABS)[number]['id']

function tabFromHash(): TabId {
  const wanted = window.location.hash.replace('#', '')
  return TABS.find(tab => tab.id === wanted)?.id ?? 'heals'
}

export default function ReplayApp() {
  const [data, setData] = useState<ReplayData | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<TabId>(tabFromHash)
  const [selectedHeal, setSelectedHeal] = useState('')

  useEffect(() => {
    let active = true
    loadReplay().then(value => {
      if (!active) return
      setData(value)
      const first = value.heals[0]
      if (first) setSelectedHeal(`${first.run}-${first.heal_id}`)
    }).catch(reason => { if (active) setError(String(reason)) })
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => { active = false; window.removeEventListener('hashchange', onHash) }
  }, [])

  if (error) return <main className="nx nx-state" role="alert"><p className="container">{error}. Rebuild with npm run build:replay.</p></main>
  if (!data) return <main className="nx nx-state" role="status"><p className="container">Loading the recorded DEV replay…</p></main>

  const heal = data.heals.find(item => `${item.run}-${item.heal_id}` === selectedHeal) ?? data.heals[0]
  const choose = (id: TabId) => { window.location.hash = id; setTab(id) }

  return (
    <div id="top" className="nx">
      <a className="skip" href="#main">Skip to content</a>
      <Nav />
      <main id="main">
        <SectionBoundary name="headline"><Hero data={data} /></SectionBoundary>
        <SectionBoundary name="story">
          <Problem />
          <Mechanism data={data} />
          <Finding data={data} />
          <PerClass data={data} />
          <Walkthrough data={data} />
          <Architecture data={data} />
          <UseIt data={data} />
          <Limits data={data} />
        </SectionBoundary>
        <EvidenceIntro data={data}>
    <div className="explorer space-y-5">
      <header>
        <h3 className="text-xl font-semibold">Nexus · DEV replay</h3>
        <p className="text-sm mt-1 text-ink2">
          Detect, propose, check, decide: {data.heals.length} recorded heals and {data.traces.length} DEV traces.
          Read-only, static JSON, no backend or keys.
        </p>
      </header>
      <aside className="border border-rule bg-paper3 rounded-lg p-3 text-sm space-y-1" aria-label="Replay limitations">
        {data.notices.map(notice => <p key={notice}>{notice}</p>)}
      </aside>
      <nav role="tablist" aria-label="Replay views" className="flex flex-wrap gap-1 border-b border-rule">
        {TABS.map(item => (
          <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => choose(item.id)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === item.id ? 'border-accent text-ink font-medium' : 'border-transparent text-muted hover:text-ink'}`}>
            {item.label}
          </button>
        ))}
      </nav>
      {tab === 'heals' && heal && (
        <div className="space-y-5">
          <HealPicker heals={data.heals} selected={`${heal.run}-${heal.heal_id}`} onSelect={setSelectedHeal} />
          <HealView data={data} heal={heal} />
        </div>
      )}
      {tab === 'traces' && <TraceView data={data} />}
      {tab === 'numbers' && <HeadlinePanel data={data} />}
      {tab === 'provenance' && <ProvenancePanel data={data} />}
    </div>
        </EvidenceIntro>
      </main>
      <Footer data={data} />
    </div>
  )
}
