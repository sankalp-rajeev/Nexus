"""services/healer — Auto-Healer & Eval Loop (Phase 5).

Workflow per PatchProposal:
  1. NOTIFICATION — Slack (optional) or autonomous auto-approve
  2. PATCH APPLICATION — writes to agent_configs, notifies Redis
  3. EVAL RE-RUN — DeepEval + Gemini scores before/after
  4. SCORE LOGGING — MLflow run with params/metrics/artifacts
  5. HEALTH DIFF — Redis pub/sub for dashboard WebSocket consumers
"""
