# Phase 6 groundwork: demo and adoption

**Date:** 2026-11-11 (America/New_York)
**Branch:** `phase-6-demo`
**Provider:** no new provider calls; committed DEV detector predictions and mock critic excerpts
**Model:** no generative model invoked; existing classifier tests use cached local embedding/NLI weights
**Mock:** replay critic templates are mock; lite critic uses deterministic generic fallbacks

## Built

The collector accepts OTLP/HTTP traces at `/v1/traces`, using JSON or binary
protobuf, with gzip support. The optional SDK integration maps GenAI
attributes to Nexus `SpanBatch` without dropping unmapped attributes. See
[the field mapping](otel-mapping.md) for exact precedence, defaults,
preservation and transport behavior. Native `/v1/spans` ingestion remains
available. Both paths use the selected queue backend.

The dashboard has a separate static replay entry. It loads only local
`replay.json`, supports selecting recorded traces and inspecting span inputs,
outputs, alerts, illustrative critic proposal excerpts and gate decisions.
Approval and rejection controls are absent. Replay does not initialize the
live app, API polling or WebSocket. The replay HTML also omits external font
links, so the static assets have no external runtime dependency. No backend,
credentials or environment file is needed. Serve the build over HTTP; opening
`index.html` as a `file:` URL is not supported by browsers' module/fetch rules.

The export script uses an explicit allowlist of five committed sources:
`data/nexusbench/splits.json`, `labels.csv`, `traces.jsonl`,
`results/phase2_dev_predictions.json`, and `results/critic_smoke_mock.json`.
It resolves Git blob IDs, then reads those immutable blobs instead of current
working files. Only DEV-labeled trace IDs whose task IDs also belong to DEV
are eligible. The mixed trace corpus is scanned by opaque ID; only selected
DEV trace content is deserialized. No TEST result file is read and no TEST
trace is exported. The deterministic selection takes the first two trace IDs
per predicted class: 12 traces, 10 alerts and 10 template projections.
Source blob hashes accompany the export.

There are no committed critic proposals evaluated on these DEV traces yet.
The replay projects generic fallback excerpts from the committed **mock**
smoke artifact onto corresponding DEV alerts for illustration. Every such
proposal carries `illustrative: true`, `excerpt_only: true`, a template source
trace ID and a visible warning. They are not new critic results. All gate
decisions say **placeholder**, with `decision: null`, until Phase 4 is final.
No before/after scores or health gains are invented. The exporter makes no
LLM calls and runs no detectors or experiments.

`docker-compose.lite.yml` defines one application process containing the
collector, bounded in-process queue, deterministic detectors and the existing
critic's generic fallback, backed by one SQLite database on a named volume.
It needs no Kafka, Timescale/Postgres, Redis, MLflow or API keys. The dedicated
collector Dockerfile installs only lite dependencies and copies the existing
detectors and critic fallback without changing their source. Host port 18000
and Compose project name `nexus-lite` isolate it from the full stack.

Lite detects loops, tool misfires, conflicting memory profiles and plan drift
using the existing deterministic implementations. NLI hallucination detection
and the optional LLM judge are disabled; it is not equivalent to the full
detector pipeline. Trace snapshots accumulate as spans arrive; without an
explicit trace completion protocol, early alerts are provisional and retained
for inspection. It does not evaluate, approve or apply patches. Gate records
are placeholders. `/v1/lite/snapshot` exposes persisted traces and artifacts
for read-only inspection; `/health` identifies the queue backend.

The worker commits each span and derived artifacts in a SQLite transaction.
Duplicate `(trace_id, span_id)` deliveries update the existing span; repeated
alerts/templates are deduplicated. Graceful shutdown drains accepted queue
items. The bounded queue is volatile before persistence: a process crash can
lose queued spans. Worker failures are logged and degrade health. This is a
single-process demo runtime, not a durable distributed queue; do not increase
Uvicorn workers or scale it into separate consumers.

## Build and run replay locally

From the repository root, with Python, Git and Node available:

```powershell
cd dashboard
npm.cmd ci
npm.cmd run build:replay
python -m http.server 4173 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:4173`. On shells without PowerShell's script policy
restriction, `npm` works in place of `npm.cmd`. The build command automatically
regenerates `public/replay.json` from committed inputs. Copy `dashboard/dist/`
to any static HTTP host, including a subdirectory. Git is needed only at export
time, not by the deployed replay. The tracked JSON is a reviewable snapshot;
rebuilding reproduces it while the five input blobs remain unchanged.

To regenerate JSON separately: `python dashboard/scripts/export_replay.py`
from the repository root. For the existing live build use `npm.cmd run build`;
both build commands write `dashboard/dist/`, so run `build:replay` last when
preparing the demo.

## Run lite without Docker

Install `services/collector/requirements-lite.txt` and the SDK into a local
virtual environment, then from the repository root:

```powershell
$env:NEXUS_QUEUE = 'inprocess'
$env:NEXUS_SQLITE_PATH = 'services/collector/nexus-lite.db'
$env:NEXUS_LLM = 'mock'
python -m uvicorn services.collector.main:app --host 127.0.0.1 --port 18000 --workers 1
```

Use `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:18000/v1/traces` and
`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf` with a standard OTel HTTP
exporter. The SDK exporter is optional in the instrumented application; the
collector's lite runtime only needs the protocol package. Content capture
must be enabled in the producer's instrumentation if input/output content is
desired; absent content is not reconstructed.

## Validation

Only unit and in-process tests were run. No Docker command, external service
integration, benchmark experiment, generative LLM call, push, merge or tag was
performed. The existing Python environment and Node dependencies were read
without modifying the other worktrees.

The full allowed Python suite is run with the two external-service modules
excluded so it cannot connect to the other agent's Kafka/Postgres services:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
# Point HF_HOME to your existing local model cache if needed.
python -m pytest tests --ignore=tests/integration/test_collector_kafka.py --ignore=tests/integration/test_critic_pipeline.py -q
python -m ruff check .
cd dashboard
npm.cmd run test:replay
npm.cmd run build
npm.cmd run build:replay
```

Final verification: **217 Python tests passed, 1 existing test skipped**;
**3 dashboard in-process tests passed**; `ruff check .` and `git diff --check`
were clean. Both the live production build and replay build passed TypeScript
and Vite. Inspection of the final replay assets confirmed the live ingestion
and WebSocket entry is absent and HTML references only local assets. The final
`dashboard/dist/` contains the replay build. The two external-service test
modules above remain deferred, rather than probing Phase 4's running services.

The first baseline run tried to refresh Hugging Face metadata and failed under
the network sandbox. Using the existing model cache in explicit offline mode
resolved those pre-existing classifier tests without changing classifier code
or test expectations. Tests were run using the existing Python 3.11.14 project
environment. Upstream Google SDK deprecation and Browserslist age warnings
remain non-failing.

## Docker validation still required

After Phase 4 experiments finish, the user can schedule:

1. Build and start `docker compose -f docker-compose.lite.yml up --build`;
   check image dependencies, health check, bind address and named-volume permissions.
2. Send both native spans and a standard OTel HTTP export through the host port;
   inspect `/v1/lite/snapshot` for traces, alerts, fallback proposals and placeholders.
3. Restart the container and confirm SQLite persistence; verify shutdown draining
   and behavior under queue saturation and database write errors.
4. Run the deferred full-stack Kafka/Postgres integration modules separately,
   and check the existing Kafka collector image with the new protocol dependency.

When Phase 4 becomes final, a separate follow-up can export committed DEV gate
results and genuinely evaluated DEV proposals. Keep placeholders until then.
README and results artifacts were intentionally left untouched.
