import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'replay' ? [{
    name: 'offline-replay-html',
    // Also protect direct `vite build --mode replay` invocations.
    apply: 'build' as const,
    buildStart() {
      execFileSync('python', [fileURLToPath(new URL('./scripts/export_replay.py', import.meta.url))], { stdio: 'inherit' })
    },
    transformIndexHtml(html: string) {
      return html.replace(/\s*<link[^>]*https:\/\/fonts\.[^>]*>/g, '')
        .replace('<title>Nexus', '<title>DEV Replay · Nexus')
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
