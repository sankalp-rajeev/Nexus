import type { AgentHealth } from '../types'

function HealthRing({ score }: { score: number }) {
  const size = 64
  const stroke = 5
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const dash = Math.max(0, Math.min(1, score)) * circ

  let color = '#16a34a'
  if (score < 0.8) color = '#d97706'
  if (score < 0.6) color = '#dc2626'

  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="#e7e5e4" strokeWidth={stroke}
      />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke={color} strokeWidth={stroke}
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        style={{ transition: 'stroke-dasharray 0.6s ease' }}
      />
    </svg>
  )
}

function AgentCard({ agent }: { agent: AgentHealth }) {
  const score = agent.health_score ?? 0
  const pct = Math.round(score * 100)

  let textColor = 'text-emerald-700'
  let label = 'Healthy'
  if (score < 0.8) { textColor = 'text-amber-600'; label = 'Degraded' }
  if (score < 0.6) { textColor = 'text-rose-600'; label = 'Unhealthy' }

  function fmtTime(ts: string) {
    try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
    catch { return '' }
  }

  return (
    <article className="flex items-center gap-4 p-4 border border-stone-200 rounded-lg hover:border-stone-300 transition-colors">
      <div className="relative shrink-0">
        <HealthRing score={score} />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`font-mono font-semibold text-sm ${textColor} tabular-nums`}>
            {pct}
          </span>
        </div>
      </div>

      <div className="flex-1 min-w-0">
        <p className="font-semibold text-stone-800 text-sm truncate">{agent.agent_name}</p>
        <p className={`text-xs font-medium ${textColor} mt-0.5`}>{label}</p>
        {agent.last_failure_type && (
          <p className="text-xs text-stone-400 font-mono mt-0.5 truncate">
            Last: {agent.last_failure_type}
            {agent.last_eval_at ? ` · ${fmtTime(agent.last_eval_at)}` : ''}
          </p>
        )}
        <p className="text-xs text-stone-300 font-mono mt-0.5">
          {agent.eval_count} eval{agent.eval_count !== 1 ? 's' : ''} this hour
        </p>
      </div>
    </article>
  )
}

export default function HealthScore({ agents }: { agents: AgentHealth[] }) {
  return (
    <section className="flex flex-col h-full">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-stone-800 tracking-tight">Agent Health</h2>
        <p className="text-xs text-stone-400 font-mono mt-0.5">Rolling 1-hour average</p>
      </header>

      <div className="flex-1 overflow-y-auto space-y-2">
        {agents.length === 0 ? (
          <div className="py-12 text-center text-stone-300 font-mono text-xs">
            No instrumented agents yet
          </div>
        ) : (
          agents.map(a => <AgentCard key={a.agent_name} agent={a} />)
        )}
      </div>
    </section>
  )
}
