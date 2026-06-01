import { useCallback, useEffect, useState } from 'react'
import { Wifi, WifiOff, Activity } from 'lucide-react'
import TraceStream from './components/TraceStream'
import FailureTimeline from './components/FailureTimeline'
import CriticPanel from './components/CriticPanel'
import PatchHistory from './components/PatchHistory'
import HealthScore from './components/HealthScore'
import { useWebSocket } from './hooks/useWebSocket'
import type {
  AgentHealth,
  EvalRun,
  PatchProposal,
  Span,
  TimelineBucket,
  WSMessage,
} from './types'

const API = ''  // proxied by Vite dev server; empty in prod (same origin)
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/traces`

function useInitialData() {
  const [spans, setSpans] = useState<Span[]>([])
  const [proposals, setProposals] = useState<PatchProposal[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [agents, setAgents] = useState<AgentHealth[]>([])
  const [timeline, setTimeline] = useState<TimelineBucket[]>([])

  useEffect(() => {
    const load = async () => {
      const [s, p, r, a, t] = await Promise.allSettled([
        fetch(`${API}/v1/spans`).then(r => r.json()),
        fetch(`${API}/v1/patches`).then(r => r.json()),
        fetch(`${API}/v1/patches/history`).then(r => r.json()),
        fetch(`${API}/v1/agents/health`).then(r => r.json()),
        fetch(`${API}/v1/timeline`).then(r => r.json()),
      ])
      if (s.status === 'fulfilled' && Array.isArray(s.value)) setSpans(s.value)
      if (p.status === 'fulfilled' && Array.isArray(p.value)) setProposals(p.value)
      if (r.status === 'fulfilled' && Array.isArray(r.value)) setRuns(r.value)
      if (a.status === 'fulfilled' && Array.isArray(a.value)) setAgents(a.value)
      if (t.status === 'fulfilled' && Array.isArray(t.value)) setTimeline(t.value)
    }
    load()
    const interval = setInterval(load, 15_000)  // refresh every 15s
    return () => clearInterval(interval)
  }, [])

  return { spans, setSpans, proposals, setProposals, runs, setRuns, agents, setAgents, timeline }
}

export default function App() {
  const { spans, setSpans, proposals, setProposals, runs, setRuns, agents, setAgents, timeline } =
    useInitialData()

  const handleMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'span') {
      setSpans(prev => [msg.data as Span, ...prev].slice(0, 50))
    } else if (msg.type === 'patch_proposal') {
      const p = msg.data as PatchProposal
      setProposals(prev => {
        const exists = prev.some(x => x.proposal_id === p.proposal_id)
        return exists ? prev : [p, ...prev]
      })
    } else if (msg.type === 'health_diff') {
      const h = msg.data as AgentHealth
      if (h.agent_name) {
        setAgents(prev => {
          const idx = prev.findIndex(a => a.agent_name === h.agent_name)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...h }
            return next
          }
          return [h, ...prev]
        })
      }
    }
  }, [setSpans, setProposals, setAgents])

  const connected = useWebSocket(WS_URL, handleMessage)

  const pendingCount = proposals.filter(p => p.status === 'PENDING_REVIEW').length

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col">
      {/* ── Top bar ── */}
      <header className="h-12 border-b border-stone-200 bg-white flex items-center px-6 gap-4 shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-orange-600" />
          <span className="font-semibold text-stone-800 tracking-tight text-sm">Nexus</span>
          <span className="text-stone-300 text-xs font-mono">AI Agent Monitor</span>
        </div>

        <div className="flex-1" />

        {pendingCount > 0 && (
          <span className="text-xs font-mono bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full">
            {pendingCount} pending
          </span>
        )}

        <div className="flex items-center gap-1.5 text-xs font-mono">
          {connected ? (
            <><Wifi size={12} className="text-emerald-500" /><span className="text-emerald-600">live</span></>
          ) : (
            <><WifiOff size={12} className="text-rose-400" /><span className="text-rose-500">connecting…</span></>
          )}
        </div>
      </header>

      {/* ── Main grid ── */}
      <main className="flex-1 grid grid-cols-12 gap-px bg-stone-200 overflow-hidden" style={{ height: 'calc(100vh - 3rem)' }}>

        {/* TraceStream — left third */}
        <div className="col-span-4 bg-white p-5 overflow-hidden flex flex-col">
          <TraceStream spans={spans} />
        </div>

        {/* Center column — top: timeline, bottom: patch history */}
        <div className="col-span-5 flex flex-col gap-px bg-stone-200 overflow-hidden">
          <div className="bg-white p-5 overflow-hidden flex flex-col" style={{ height: '45%' }}>
            <FailureTimeline buckets={timeline} />
          </div>
          <div className="bg-white p-5 overflow-hidden flex flex-col flex-1">
            <PatchHistory runs={runs} />
          </div>
        </div>

        {/* Right column — top: health, bottom: critic */}
        <div className="col-span-3 flex flex-col gap-px bg-stone-200 overflow-hidden">
          <div className="bg-white p-5 overflow-hidden flex flex-col" style={{ height: '40%' }}>
            <HealthScore agents={agents} />
          </div>
          <div className="bg-white p-5 overflow-hidden flex flex-col flex-1">
            <CriticPanel proposals={proposals} />
          </div>
        </div>

      </main>
    </div>
  )
}
