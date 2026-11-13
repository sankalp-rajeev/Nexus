import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Replay builds publish public/replay.json, which is generated and reviewed offline
// (dashboard/scripts/export_replay.py). The build never regenerates it; it only refuses to
// ship a missing, malformed or placeholder-bearing file.
function assertReplayPublishable() {
  const path = fileURLToPath(new URL('./public/replay.json', import.meta.url))
  if (!existsSync(path)) {
    throw new Error('public/replay.json is missing: run `npm run export:replay` and commit it')
  }
  const text = readFileSync(path, 'utf-8')
  const data = JSON.parse(text)
  if (data.schema_version !== 2 || data.mode !== 'replay' || data.split !== 'dev' || data.read_only !== true) {
    throw new Error('public/replay.json is not a read-only DEV replay (schema 2)')
  }
  if (/placeholder|mock/i.test(text)) {
    throw new Error('public/replay.json contains placeholder or mock content')
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'replay' ? [{
    name: 'offline-replay-html',
    // Also protects direct `vite build --mode replay` invocations.
    apply: 'build' as const,
    buildStart() {
      assertReplayPublishable()
    },
    transformIndexHtml(html: string) {
      return html.replace(/\s*<link[^>]*https:\/\/fonts\.[^>]*>/g, '')
        .replace('<title>Nexus', '<title>DEV replay - Nexus')
    },
  }] : [])],
  server: {
    port: 3000,
    proxy: {
      '/v1': 'http://localhost:8001',
      '/ws': { target: 'ws://localhost:8001', ws: true },
    },
  },
}))
