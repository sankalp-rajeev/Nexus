import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { test } from 'node:test'
import { build } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

// In-process component/data-loader checks, with no browser or HTTP server.
await mkdir('.vite/replay-tests', { recursive: true })
async function loadModule(entry, name) {
  const result = await build({
    entryPoints: [entry], bundle: true, write: false, platform: 'node',
    format: 'esm', packages: 'external', jsx: 'automatic',
    define: { 'import.meta.env.BASE_URL': '"./"' },
  })
  const path = `.vite/replay-tests/${name}.mjs`
  await writeFile(path, result.outputFiles[0].text)
  return import(new URL(`../${path}`, import.meta.url))
}
const { default: CriticPanel } = await loadModule('src/components/CriticPanel.tsx', 'critic')
const { loadReplay, validateReplay, sourceUrl, STAGES } = await loadModule('src/replay.ts', 'loader')
const { default: HealView } = await loadModule('src/replay/HealView.tsx', 'heal')
const { default: HealTimeline, healSteps } = await loadModule('src/replay/HealTimeline.tsx', 'timeline')
const { default: HeadlinePanel } = await loadModule('src/replay/HeadlinePanel.tsx', 'headline')
const { default: ProvenancePanel } = await loadModule('src/replay/ProvenancePanel.tsx', 'provenance')
const { default: TraceView } = await loadModule('src/replay/TraceView.tsx', 'traces')

const text = await readFile('public/replay.json', 'utf-8')
const data = validateReplay(JSON.parse(text))
const render = (element) => renderToStaticMarkup(element)

const proposal = {
  proposal_id: 'p', trace_id: 'dev', alert_id: 'a', status: 'PENDING_REVIEW',
  failure_type: 'LOOP_DETECTED', patch_type: 'RETRY_POLICY_PATCH', confidence: 'LOW',
  target_component: 'loop', explanation: 'Recorded fallback proposal', patch_content: 'excerpt',
}

test('read-only critic panel has no mutation controls; the live one keeps them', () => {
  const html = render(React.createElement(CriticPanel, { proposals: [proposal], readOnly: true }))
  assert.match(html, /Recorded proposals/)
  assert.doesNotMatch(html, /<button|Approve|Reject/)
  const live = render(React.createElement(CriticPanel, { proposals: [proposal] }))
  assert.match(live, /Approve/)
  assert.match(live, /Reject/)
})

test('replay fetches only local JSON and rejects TEST, old or incompatible exports', async () => {
  const calls = []
  const original = globalThis.fetch
  const sample = JSON.parse(text)
  try {
    globalThis.fetch = async (...args) => { calls.push(args); return { ok: true, json: async () => sample } }
    assert.deepEqual(await loadReplay(), sample)
    assert.deepEqual(calls, [['./replay.json']])
    sample.split = 'test'
    await assert.rejects(loadReplay, /read-only DEV/)
    sample.split = 'dev'
    sample.schema_version = 1
    await assert.rejects(loadReplay, /schema version 2/)
    globalThis.fetch = async () => ({ ok: false, status: 404 })
    await assert.rejects(loadReplay, /unavailable \(404\)/)
  } finally {
    globalThis.fetch = original
  }
})

test('the shipped replay.json is DEV-only and free of placeholder or mock text', () => {
  assert.equal(data.split, 'dev')
  assert.doesNotMatch(text, /placeholder|mock/i)
  assert.ok(data.heals.length >= 8 && data.heals.length <= 12)
  assert.ok(data.traces.length >= 12)
})

test('every heal renders the six stages in order with their recorded outcomes', () => {
  for (const heal of data.heals) {
    const steps = healSteps(heal)
    assert.deepEqual(steps.map(step => step.name), [...STAGES])
    const html = render(React.createElement(HealTimeline, { heal }))
    const order = [...html.matchAll(/data-step="([^"]+)" data-state="([^"]+)"/g)]
    assert.deepEqual(order.map(m => m[1]), [...STAGES])
    const checks = Object.fromEntries(heal.gate.checks.map(c => [c.label, c.outcome]))
    for (const [, name, state] of order) {
      if (name in checks) assert.equal(state, checks[name])
    }
    assert.equal(order.at(-1)[2], heal.gate.decision === 'promoted' ? 'pass' : 'fail')
  }
})

test('heal view shows the trace, detector verdict, critic patch and each gate check', () => {
  for (const heal of data.heals) {
    const html = render(React.createElement(HealView, { data, heal }))
    assert.ok(html.includes(heal.heal_id))
    assert.ok(html.includes(heal.detector.verdict))
    for (const check of heal.gate.checks) assert.ok(html.includes(check.label), check.label)
    if (heal.critic.status === 'patch') assert.ok(html.includes(heal.critic.patch_type))
  }
  const outcomes = new Set(data.heals.map(h => h.gate.decision))
  assert.deepEqual([...outcomes].sort(), ['promoted', 'rejected'])
})

test('headline panel shows every number with a link to its source file', () => {
  const html = render(React.createElement(HeadlinePanel, { data }))
  const items = data.headline.groups.flatMap(g => g.items)
  assert.ok(items.length >= 10)
  for (const item of items) {
    assert.ok(html.includes(item.value.replaceAll('&', '&amp;')) || html.includes(item.value), item.id)
    assert.ok(html.includes(sourceUrl(data, item.source.path)), item.id)
  }
})

test('provenance and trace views render the recorded statement and traces', () => {
  const provenance = render(React.createElement(ProvenancePanel, { data }))
  assert.ok(provenance.includes(data.provenance.generated_from_commit))
  assert.ok(provenance.includes('TEST numbers shown only as already reported in RESULTS.md'))
  const traces = render(React.createElement(TraceView, { data }))
  assert.ok(traces.includes(data.traces[0].trace_id))
})
