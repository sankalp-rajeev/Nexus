import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
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
const { loadReplay } = await loadModule('src/replay.ts', 'loader')
const proposal = {
  proposal_id: 'p', trace_id: 'dev', alert_id: 'a', status: 'PENDING_REVIEW',
  failure_type: 'LOOP_DETECTED', patch_type: 'RETRY_POLICY_PATCH', confidence: 'LOW',
  target_component: 'loop', explanation: 'Generic mock fallback template excerpt', patch_content: 'excerpt',
}

test('replay critic renders recorded proposals without mutation controls', () => {
  const html = renderToStaticMarkup(React.createElement(CriticPanel, { proposals: [proposal], readOnly: true }))
  assert.match(html, /Illustrative mock template excerpts/)
  assert.match(html, /Generic mock fallback/)
  assert.doesNotMatch(html, /<button|Approve|Reject/)
})

test('live critic retains approval controls', () => {
  const html = renderToStaticMarkup(React.createElement(CriticPanel, { proposals: [proposal] }))
  assert.match(html, /Approve/)
  assert.match(html, /Reject/)
})

test('replay fetches only local JSON and rejects TEST or incompatible exports', async () => {
  const calls = []
  const original = globalThis.fetch
  const data = { schema_version: 1, mode: 'replay', split: 'dev', read_only: true, traces: [], alerts: [], proposals: [], gate_decisions: [], notices: [] }
  try {
    globalThis.fetch = async (...args) => { calls.push(args); return { ok: true, json: async () => data } }
    assert.deepEqual(await loadReplay(), data)
    assert.deepEqual(calls, [['./replay.json']])
    data.split = 'test'
    await assert.rejects(loadReplay, /read-only DEV/)
    globalThis.fetch = async () => ({ ok: false, status: 404 })
    await assert.rejects(loadReplay, /unavailable \(404\)/)
  } finally {
    globalThis.fetch = original
  }
})
