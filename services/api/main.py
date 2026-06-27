"""Nexus API — main application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from services.api.routes import agents, patches, traces
from services.api.ws_manager import (
    db_poll_loop,
    keepalive_loop,
    manager,
    redis_subscriber_loop,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nexus.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.api.db import get_connection
    tasks = [
        asyncio.create_task(keepalive_loop()),
        asyncio.create_task(redis_subscriber_loop(
            os.getenv("REDIS_HOST", "localhost"))),
        asyncio.create_task(db_poll_loop(get_connection)),
    ]
    logger.info("nexus-api: started (WebSocket + background tasks active)")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Nexus API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(traces.router)
app.include_router(patches.router)
app.include_router(agents.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "nexus-api"}


@app.websocket("/ws/traces")
async def ws_traces(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial data snapshot on connect
        from services.api.db import (
            fetch_agent_health,
            fetch_patches,
            fetch_recent_spans,
            get_connection,
        )
        try:
            conn = get_connection()
            spans = fetch_recent_spans(conn, limit=20)
            pending = fetch_patches(conn, status="PENDING_REVIEW", limit=5)
            health = fetch_agent_health(conn)
            conn.close()
            for span in reversed(spans):
                await websocket.send_json({"type": "span", "data": span})
            for p in pending:
                await websocket.send_json({"type": "patch_proposal", "data": p})
            for h in health:
                await websocket.send_json({"type": "health_diff", "data": h})
        except Exception as exc:
            logger.warning("api: initial snapshot failed: %s", exc)

        # Keep connection alive (client sends pings)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.getenv("API_PORT", "8001")), log_level="info")
