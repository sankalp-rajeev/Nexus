import { useEffect, useState } from 'react'
import CriticPanel from './components/CriticPanel'
import TraceStream from './components/TraceStream'
import { loadReplay, type ReplayData } from './replay'

export default function ReplayApp() {
  const [data, setData] = useState<ReplayData | null>(null)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    loadReplay().then(value => {
      if (active) { setData(value); setSelected(value.traces[0]?.trace_id ?? '') }
    }).catch(reason => { if (active) setError(String(reason)) })
    return () => { active = false }
  }, [])
  if (error) return <main className="p-8" role="alert">{error}. Rebuild with npm run build:replay.</main>
  if (!data) return <main className="p-8" role="status">Loading committed DEV replay…</main>
  const trace = data.traces.find(item => item.trace_id === selected)
  const alerts = data.alerts.filter(item => item.trace_id === selected)
  const gates = data.gate_decisions.filter(item => item.trace_id === selected)
  return (
    <main className="min-h-screen bg-stone-50 text-stone-800 p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Nexus · DEV replay</h1>
        <p className="text-sm mt-1">Read-only · static JSON · no backend or keys</p>
      </header>
      <aside className="border border-amber-300 bg-amber-50 p-4 text-sm space-y-1" aria-label="Replay limitations">
        {data.notices.map(notice => <p key={notice}>{notice}</p>)}
      </aside>
      <label className="block text-sm">
        Trace ({data.traces.length} committed DEV runs)
        <select value={selected} onChange={event => setSelected(event.target.value)} className="block mt-2 border border-stone-300 bg-white p-2 max-w-full">
          {data.traces.map(item => <option key={item.trace_id} value={item.trace_id}>{item.trace_id} · {item.agent_name}</option>)}
        </select>
      </label>
      {trace && <>
        <section className="grid lg:grid-cols-2 gap-6">
          <div className="space-y-4">
            <h2 className="font-semibold">Recorded run</h2>
            <p className="text-sm whitespace-pre-wrap">{trace.root_input}</p>
            <details className="text-sm"><summary className="cursor-pointer">Recorded final output</summary><p className="mt-2 whitespace-pre-wrap">{trace.final_output ?? 'No final output recorded.'}</p></details>
            <h2 className="font-semibold">Alerts</h2>
            {alerts.length ? alerts.map(alert => <p key={alert.alert_id} className="text-sm">{alert.failure_type} · {alert.status} · committed detector prediction</p>) : <p className="text-sm">No alert: committed detector prediction is NORMAL.</p>}
            <h2 className="font-semibold">Gate decisions · placeholder</h2>
            {gates.length ? gates.map((gate, i) => <p key={i} className="text-sm">{gate.reason}</p>) : <p className="text-sm">No proposal gate for this trace. Phase 4 results remain pending.</p>}
            <p className="text-sm text-stone-500">Evaluation scores and health gains are unavailable until Phase 4 is final.</p>
          </div>
          <div className="bg-white border border-stone-200 p-4">
            <CriticPanel proposals={data.proposals.filter(item => item.trace_id === selected)} readOnly />
          </div>
        </section>
        <div className="bg-white border border-stone-200 p-4">
          <TraceStream spans={trace.spans.map(span => ({ ...span, server_timestamp: span.server_timestamp || span.client_timestamp || '' }))} replay />
        </div>
        <details className="text-sm"><summary className="cursor-pointer">Span inputs, outputs and attributes</summary><pre className="mt-2 p-3 bg-stone-100 overflow-auto max-h-96 whitespace-pre-wrap">{JSON.stringify(trace.spans, null, 2)}</pre></details>
      </>}
      <details className="text-sm"><summary className="cursor-pointer">Committed source provenance</summary><pre className="mt-2 overflow-auto">{JSON.stringify(data.provenance, null, 2)}</pre></details>
    </main>
  )
}
