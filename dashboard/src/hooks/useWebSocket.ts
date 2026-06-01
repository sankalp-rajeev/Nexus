import { useEffect, useRef, useState } from 'react'
import type { WSMessage } from '../types'

type Handler = (msg: WSMessage) => void

export function useWebSocket(url: string, onMessage: Handler) {
  const [connected, setConnected] = useState(false)
  const ws = useRef<WebSocket | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>

    function connect() {
      try {
        const socket = new WebSocket(url)
        ws.current = socket

        socket.onopen = () => setConnected(true)
        socket.onclose = () => {
          setConnected(false)
          reconnectTimer = setTimeout(connect, 3000)
        }
        socket.onerror = () => socket.close()
        socket.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data) as WSMessage
            onMessageRef.current(msg)
          } catch {}
        }
      } catch {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      clearTimeout(reconnectTimer)
      ws.current?.close()
    }
  }, [url])

  return connected
}
