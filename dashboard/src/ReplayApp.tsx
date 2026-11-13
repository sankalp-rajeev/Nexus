import { useEffect, useState } from 'react'
import { loadReplay, type ReplayData } from './replay'
import HeadlinePanel from './replay/HeadlinePanel'
import HealView, { HealPicker } from './replay/HealView'
import ProvenancePanel from './replay/ProvenancePanel'
import TraceView from './replay/TraceView'

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

  if (error) return <main className="p-8" role="alert">{error}. Rebuild with npm run build:replay.</main>
  if (!data) return <main className="p-8" role="status">Loading the recorded DEV replay…</main>

  const heal = data.heals.find(item => `${item.run}-${item.heal_id}` === selectedHeal) ?? data.heals[0]
  const choose = (id: TabId) => { window.location.hash = id; setTab(id) }

  return (
    <main className="min-h-screen bg-stone-50 text-stone-800 px-4 sm:px-6 py-5 space-y-5 max-w-7xl mx-auto">
      <header>
        <h1 className="text-xl font-semibold">Nexus · DEV replay</h1>
        <p className="text-sm mt-1 text-stone-600">
          Detect, propose, check, decide: {data.heals.length} recorded heals and {data.traces.length} DEV traces.
          Read-only, static JSON, no backend or keys.
        </p>
      </header>
      <aside className="border border-amber-300 bg-amber-50 rounded-lg p-3 text-xs space-y-1" aria-label="Replay limitations">
        {data.notices.map(notice => <p key={notice}>{notice}</p>)}
      </aside>
      <nav role="tablist" aria-label="Replay views" className="flex flex-wrap gap-1 border-b border-stone-200">
        {TABS.map(item => (
          <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => choose(item.id)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === item.id ? 'border-stone-800 font-semibold' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>
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
    </main>
  )
}
