import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'replay' ? [{
    name: 'offline-replay-html',
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
