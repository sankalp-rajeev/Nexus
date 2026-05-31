-- infra/init/postgres_init.sql
-- Nexus persistent storage schema (TimescaleDB on PostgreSQL 15).
-- Source: NEXUS_PRD.md Section 13.2.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE traces (
    trace_id        TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    environment     TEXT NOT NULL DEFAULT 'development',
    root_input      TEXT,                           -- Input to the first span
    final_output    TEXT,                           -- Output from the last span
    span_count      INTEGER DEFAULT 0,
    total_duration_ms FLOAT,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    status          TEXT DEFAULT 'in_progress'      -- in_progress | completed | failed
);

CREATE TABLE spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    parent_span_id  TEXT,
    agent_name      TEXT NOT NULL,
    span_type       TEXT NOT NULL,
    input           TEXT,
    output          TEXT,
    duration_ms     FLOAT,
    error_type      TEXT,
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}',
    client_timestamp TIMESTAMPTZ NOT NULL,
    server_timestamp TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('spans', 'server_timestamp');  -- TimescaleDB time partitioning
CREATE INDEX ON spans (trace_id, server_timestamp DESC);
CREATE INDEX ON spans (agent_name, span_type, server_timestamp DESC);

CREATE TABLE classifications (
    classification_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    failure_type    TEXT NOT NULL,
    anomaly_score   FLOAT,                          -- PatchCore distance
    confidence      FLOAT,                          -- Classifier confidence 0-1
    triggered_rule  TEXT,                           -- If rule-based: rule name; if ML: 'patchcore'
    failure_span_id TEXT REFERENCES spans(span_id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alerts (
    alert_id        TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    classification_id TEXT REFERENCES classifications(classification_id),
    agent_name      TEXT NOT NULL,
    failure_type    TEXT NOT NULL,
    severity        TEXT DEFAULT 'HIGH',            -- HIGH | MEDIUM | LOW
    status          TEXT DEFAULT 'OPEN',            -- OPEN | ACKNOWLEDGED | RESOLVED
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE TABLE patches (
    proposal_id     TEXT PRIMARY KEY,
    alert_id        TEXT NOT NULL REFERENCES alerts(alert_id),
    trace_id        TEXT NOT NULL,
    failure_type    TEXT NOT NULL,
    patch_type      TEXT NOT NULL,
    target_component TEXT NOT NULL,
    explanation     TEXT NOT NULL,
    patch_content   TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    estimated_impact TEXT,
    root_cause_analysis TEXT,
    status          TEXT DEFAULT 'PENDING_REVIEW',  -- PENDING_REVIEW | APPROVED | REJECTED | APPLIED
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    applied_at      TIMESTAMPTZ
);

CREATE TABLE eval_runs (
    run_id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    patch_id        TEXT REFERENCES patches(proposal_id),
    trace_id        TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    before_score    FLOAT,
    after_score     FLOAT,
    score_delta     FLOAT GENERATED ALWAYS AS (after_score - before_score) STORED,
    per_metric_scores JSONB DEFAULT '{}',
    eval_duration_ms FLOAT,
    mlflow_run_id   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE agent_configs (
    config_id       TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    component_name  TEXT NOT NULL,
    config_type     TEXT NOT NULL,
    content         TEXT NOT NULL,
    version         INTEGER DEFAULT 1,
    applied_patch_id TEXT REFERENCES patches(proposal_id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
