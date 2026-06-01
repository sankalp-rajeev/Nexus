"""Nexus API — FastAPI service exposing REST + WebSocket endpoints for the
dashboard. Reads from Postgres + subscribes to Redis pub/sub channels.

Routes:
  GET  /v1/spans                  — latest spans (for TraceStream)
  GET  /v1/traces                 — recent complete traces
  GET  /v1/patches                — patch proposals (PENDING_REVIEW first)
  POST /v1/patches/{id}/approve   — approve a patch
  POST /v1/patches/{id}/reject    — reject a patch
  GET  /v1/agents/health          — health score per agent
  WS   /ws/traces                 — real-time WebSocket feed
  GET  /healthz                   — liveness probe
"""
