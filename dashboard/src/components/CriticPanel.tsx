import { useState } from 'react'
import { CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react'
import type { PatchProposal } from '../types'

const CONFIDENCE_STYLE: Record<string, string> = {
  HIGH:   'text-emerald-700 bg-emerald-50 border-emerald-200',
  MEDIUM: 'text-amber-700 bg-amber-50 border-amber-200',
  LOW:    'text-rose-700 bg-rose-50 border-rose-200',
}

const FAILURE_STYLE: Record<string, string> = {
  HALLUCINATION: 'text-violet-700 bg-violet-50',
  TOOL_MISFIRE:  'text-orange-700 bg-orange-50',
  LOOP_DETECTED: 'text-red-700 bg-red-50',
  PLAN_DRIFT:    'text-sky-700 bg-sky-50',
  CONTEXT_BLEED: 'text-teal-700 bg-teal-50',
}

function ProposalCard({
  proposal,
  onApprove,
  onReject,
}: {
  proposal: PatchProposal
  onApprove: (id: string) => void
  onReject: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const isPending = proposal.status === 'PENDING_REVIEW'

  return (
    <article className="border border-stone-200 rounded-lg overflow-hidden">
      <header
        className="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-stone-50/60 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-mono font-medium px-2 py-0.5 rounded ${FAILURE_STYLE[proposal.failure_type] ?? 'text-stone-600 bg-stone-100'}`}>
              {proposal.failure_type}
            </span>
            <span className={`text-xs font-mono font-medium px-2 py-0.5 rounded border ${CONFIDENCE_STYLE[proposal.confidence] ?? ''}`}>
              {proposal.confidence}
            </span>
            <span className="text-xs text-stone-400 font-mono">{proposal.patch_type}</span>
          </div>
          <p className="text-xs text-stone-600 mt-1.5 leading-relaxed line-clamp-2">
            {proposal.explanation}
          </p>
          <p className="text-xs text-stone-400 font-mono mt-1">
            {proposal.target_component}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 pt-0.5">
          {isPending ? (
            <>
              <button
                onClick={e => { e.stopPropagation(); onApprove(proposal.proposal_id) }}
                className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-emerald-600 text-white hover:bg-emerald-700 transition-colors font-medium"
              >
                <CheckCircle size={11} /> Approve
              </button>
              <button
                onClick={e => { e.stopPropagation(); onReject(proposal.proposal_id) }}
                className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-stone-200 text-stone-500 hover:border-rose-300 hover:text-rose-600 transition-colors"
              >
                <XCircle size={11} /> Reject
              </button>
            </>
          ) : (
            <span className="text-xs font-mono text-stone-400 px-2 py-1">
              {proposal.status}
            </span>
          )}
          {expanded ? <ChevronUp size={14} className="text-stone-400" /> : <ChevronDown size={14} className="text-stone-400" />}
        </div>
      </header>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-stone-100 bg-stone-50/40">
          {proposal.root_cause_analysis && (
            <div className="mb-3">
              <p className="text-xs font-medium text-stone-500 mb-1">Root Cause</p>
              <p className="text-xs text-stone-600 leading-relaxed">{proposal.root_cause_analysis}</p>
            </div>
          )}
          <div>
            <p className="text-xs font-medium text-stone-500 mb-1">Proposed Patch</p>
            <pre className="text-xs font-mono bg-stone-100 text-stone-700 p-3 rounded-md overflow-x-auto leading-relaxed whitespace-pre-wrap">
              {proposal.patch_content}
            </pre>
          </div>
          {proposal.estimated_impact && (
            <p className="text-xs text-stone-400 mt-2 font-mono">
              Impact: {proposal.estimated_impact}
            </p>
          )}
        </div>
      )}
    </article>
  )
}

export default function CriticPanel({ proposals }: { proposals: PatchProposal[] }) {
  const [items, setItems] = useState(proposals)

  // Sync external updates (WebSocket)
  if (proposals.length !== items.length) setItems(proposals)

  async function handleApprove(id: string) {
    try {
      await fetch(`/v1/patches/${id}/approve`, { method: 'POST' })
      setItems(prev => prev.map(p =>
        p.proposal_id === id ? { ...p, status: 'APPROVED' } : p
      ))
    } catch {}
  }

  async function handleReject(id: string) {
    try {
      await fetch(`/v1/patches/${id}/reject`, { method: 'POST' })
      setItems(prev => prev.map(p =>
        p.proposal_id === id ? { ...p, status: 'REJECTED' } : p
      ))
    } catch {}
  }

  return (
    <section className="flex flex-col h-full">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-stone-800 tracking-tight">Critic Panel</h2>
        <p className="text-xs text-stone-400 font-mono mt-0.5">
          {items.filter(p => p.status === 'PENDING_REVIEW').length} pending review
        </p>
      </header>

      <div className="flex-1 overflow-y-auto space-y-2">
        {items.length === 0 ? (
          <div className="py-12 text-center text-stone-300 font-mono text-xs">
            No proposals yet
          </div>
        ) : (
          items.map(p => (
            <ProposalCard
              key={p.proposal_id}
              proposal={p}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ))
        )}
      </div>
    </section>
  )
}
