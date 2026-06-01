"""WebSocket connection manager + Redis pub/sub broadcast."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("nexus.api.ws")


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events to all."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws: client connected (total=%d)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("ws: client disconnected (total=%d)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, default=str)
        dead: set[WebSocket] = set()
        async with self._lock:
            conns = set(self._connections)
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                self._connections -= dead

    async def send_ping(self) -> None:
        await self.broadcast({"type": "ping",
                               "ts": datetime.now(timezone.utc).isoformat()})


manager = ConnectionManager()


async def keepalive_loop() -> None:
    """Send ping every 30 seconds to all connected clients."""
    while True:
        await asyncio.sleep(30)
        await manager.send_ping()


async def redis_subscriber_loop(redis_url: str) -> None:
    """Subscribe to Redis channels and broadcast events to WebSocket clients.

    Channels:
      nexus:spans        — new spans from collector/classifier
      nexus:alerts:*     — new alert events
      nexus:patches:new  — new patch proposals from critic
      nexus:health:*     — HealthDiff events from healer
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("ws: redis.asyncio not available; real-time Redis updates disabled")
        return

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    while True:
        try:
            client = aioredis.Redis(host=redis_host, port=redis_port,
                                    decode_responses=True)
            async with client.pubsub() as ps:
                await ps.psubscribe("nexus:spans", "nexus:alerts",
                                    "nexus:patches:new", "nexus:health:*")
                logger.info("ws: Redis subscriber active")
                async for msg in ps.listen():
                    if msg["type"] not in ("message", "pmessage"):
                        continue
                    channel = msg.get("channel", "") or ""
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    event_type = _channel_to_type(channel)
                    await manager.broadcast({"type": event_type, "data": data})
        except Exception as exc:
            logger.warning("ws: Redis subscriber error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)


async def db_poll_loop(get_conn_fn) -> None:
    """Poll Postgres for new spans every 2 seconds; broadcast to WebSocket clients.

    Used when Redis publisher is not set up on the collector side.
    """
    last_ts: str | None = None
    while True:
        await asyncio.sleep(2)
        try:
            conn = get_conn_fn()
            with conn:
                from services.api.db import query
                if last_ts:
                    rows = query(conn, """
                        SELECT span_id, trace_id, agent_name, span_type,
                               duration_ms, error_type, server_timestamp
                        FROM spans WHERE server_timestamp > %s
                        ORDER BY server_timestamp DESC LIMIT 20
                    """, (last_ts,))
                else:
                    rows = query(conn, """
                        SELECT span_id, trace_id, agent_name, span_type,
                               duration_ms, error_type, server_timestamp
                        FROM spans ORDER BY server_timestamp DESC LIMIT 10
                    """)
                if rows:
                    last_ts = str(rows[0]["server_timestamp"])
                    for row in rows:
                        await manager.broadcast({"type": "span", "data": row})
            conn.close()
        except Exception as exc:
            logger.debug("ws: db_poll error: %s", exc)


def _channel_to_type(channel: str) -> str:
    if channel.startswith("nexus:health"):
        return "health_diff"
    if channel.startswith("nexus:patches"):
        return "patch_proposal"
    if channel.startswith("nexus:alerts"):
        return "alert"
    return "span"
