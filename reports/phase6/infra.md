# Phase 6 infrastructure and traffic isolation

Date: 2026-11-12 (America/New_York). Branch: `phase-6-demo`.

## Approved Phase 5 cleanup

Sankalp approved stopping the Phase 5 stack, removing its Kafka container
(including its writable-layer broker records), and deleting exactly its three
attached volumes. No other container or volume deletion was approved or done.

The stop used project `nexus-phase5` and all three files from
`C:/Umich/Projects/nexus-phase5`: `docker-compose.yml`,
`docker-compose.phase5.yml`, and `docker-compose.phase5-load.yml`.
After stopping, `docker inspect nexus-phase5-kafka-1` confirmed an exited
container with exactly three mounts, all of type `volume`:

- `3d98250108ede82a24abbc8dac92a35a9eb9f6c0397ff0d8f4de9e14ae115e16`
  at `/etc/kafka/secrets`.
- `a424792d54baeb5215218c8a72acb99e8b21e5e40c671b3619835ba33bfbd416`
  at `/mnt/shared/config`.
- `e3a8561690d5e4ea0ff210933075d9432f5739bb9e8ba487075d414140879b8f`
  at `/var/lib/kafka/data`.

Removed container: `nexus-phase5-kafka-1`, ID
`05679eef1962ce0618f85b989f2368292376bbf3c04817c6e6f668f2f6442c08`.
Removed volumes: exactly the three IDs above. The volume list changed from
14 entries to 11, and the container list changed from 33 entries to 32.
Every other original container and volume was retained;
the remaining Phase 5 containers are stopped. The `nexus`, `agenttxn`, `nof1`
and unrelated containers were unchanged. PostgreSQL, MLflow and Redis volumes
were retained. Before/after lists, inspect output and machine-checked inventory
differences are local evidence under ignored `data/phase6/runs/scratch/`.

Kafka's active log directory had been `/tmp/kafka-logs` in its writable layer,
not the empty `/var/lib/kafka/data` volume. Removing the approved container
also removed those active records; deleting only the volumes would not have
cleared them.

## One active stack

Phase 6 uses Compose project `nexus-phase6` from
`C:/Umich/Projects/nexus-phase6`, with fresh project volumes. Do not reuse the
Phase 5 project, containers, PostgreSQL/MLflow volumes or Redis data.
`nexus-phase5` stays stopped. For integration validation, start only fresh
Phase 6 Kafka, PostgreSQL and Redis:

```powershell
docker compose --project-name nexus-phase6 up -d --wait --wait-timeout 180 kafka postgres redis
```

This does not start the critic or healer. Test traffic must not reach a paid
consumer. Local integration tests use PostgreSQL on `127.0.0.1:55432` and
Kafka on `localhost:29092`; explicitly set these before the DEV-only runner
because its historical default PostgreSQL port is Phase 5's `55433`.

## Synthetic traffic boundary

Every future load tool must set the **boolean** span metadata field
`nexus.synthetic: true` on every generated span. Put new load tools under
`scripts/phase6/`; leave `scripts/phase5/` unchanged. A string `"true"` is not
the flag. A trace is synthetic if any span has that boolean flag, or if its
trace/span agent name or environment equals legacy `phase5-load-dev`.

The classifier still classifies synthetic traces and publishes their normal
classification record to `nexus.spans.classified`, preserving the L3 endpoint.
It suppresses publication to `nexus.alerts`, before any paid critic consumer.
The `synthetic_suppressed` counter counts classified synthetic traces and is
reported in `/health` and a `synthetic_suppressed=N` log line. Ordinary
unmarked failures continue to publish alerts. The critic and frozen code are
unchanged.

## Required offline NLI

There is no null/zero-score NLI substitute. Classifier startup verifies NLI
before creating or subscribing a Kafka consumer. Processing also requires
NLI readiness, including rule-classified traces. A missing/broken model raises
`NLIModelUnavailable` with a clear startup/consumption refusal message.
The startup worker logs the error and stops; the health server remains
observable at `/health` on port 8002 with HTTP 503, `status: unhealthy`,
`nli_ready: false`, and `consumer_running: false`. An initialized, running
consumer reports HTTP 200. The image health check uses this endpoint.

The classifier image bakes these snapshots from `.github/model-revisions.json`:

- NLI `cross-encoder/nli-MiniLM2-L6-H768` at
  `b95119ce93d3e065de6214e38cd4a97b0f2f2c6d`.
- Embeddings `sentence-transformers/all-MiniLM-L6-v2` at
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.

Hub downloads occur only in the image build's pinned staging step. Runtime
loaders use `local_files_only=True`; `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, and telemetry disabling stay enabled. The image
build loads both models under those offline flags as a check. Model weights
and scratch artifacts are excluded from Git and the Docker build context.
The existing `required_classifier_nli` test guard remains unchanged, with a
test that confirms it rejects an uninitialized scorer.

## Lite image and CI

The lite Dockerfile copies the unchanged `services/critic/proposal.py`, needed
by `fallback.py`, and runs imports of the fallback, lite worker and collector
application during the build. It does not edit critic source.

Both CI jobs use `scripts/phase5/pytest_dev_only.py -p no:deepeval`.
The test job selects `tests/unit tests/e2e` with its existing coverage flags;
the integration job selects `tests/integration` with its existing timeout.
These selections are disjoint and together cover the full local suite.
TEST remains sealed. New scratch files belong under
`data/phase6/runs/scratch/`; the old `.venv/sync_scan.py` and
`.venv/sync_frozen.py` helpers were deleted as requested.

## Step 6.1b validation

The full local DEV-only suite passed **495 tests, with 9 skipped**: eight
sealed-TEST checks and one auxiliary-file check. Its passed cases split into
483 unit/e2e tests and 12 integration tests. The first attempt started while
fresh PostgreSQL was still initializing and Kafka was creating its consumer
offset topics; it failed on those dependencies. Once the fresh infrastructure
was healthy, the full rerun passed. Ruff and the Phase 6 frozen checker passed.
All 23 tracked Phase 5 scripts matched their pre-change working-byte hashes.

Both images built successfully. The classifier build loaded NLI and embeddings
under its offline flags. The lite build imported the fallback, lite worker and
collector application successfully. Nested legacy virtualenv/test-cache
directories are excluded from Docker contexts rather than deleted.

`docker image ls` reports the classifier image size as **2.26 GB before**
(`nexus-phase5-nexus-classifier`, `cd7c75c802fb`) and **2.90 GB after**
(`nexus-phase6-nexus-classifier`, `69233e13ae8b`). These are the CLI's rounded
image-size displays, not incremental disk-use measurements.


## Step 6.1c stack validation — failed/incomplete

Measured on 2026-11-12 (America/New_York), checkout
`a18b0b8cf8755b74a21d4d785a9cb26f6e7f0686`. Machine-readable results are in
`results/phase6/stack_validation.json`. Overall validation **did not pass**.
No application, frozen code, existing fixture, CI workflow or test runner changed.

The read-only startup audit passed before Docker work. Critic connects to
Postgres/Kafka and polls; its provider factory is reached only when processing
an alert. Healer connects to Redis/Postgres and polls pending patches; evaluation
and notification run only while processing a patch. Neither startup/idle path
makes an LLM/provider call. The audit covered the entrypoints, consumers,
critic graph/provider/accounting, and healer evaluation/notification helpers.

Docker Desktop was initially unavailable and was started. Phase 5 was confirmed
stopped before and after validation. Existing Phase 6 infrastructure containers
and volumes from 6.1b were preserved: validation used service names ending in
`-61c` within project `nexus-phase6`, fresh volume names recorded in the JSON,
and normal service DNS aliases. Internal Docker networks blocked external
runtime egress; provider keys were cleared. Application services used local
images with current `services/` and `sdk/` mounted read-only from this folder.
The critic entrypoint was also mounted from this checkout. The attempted full
run used the existing Phase 5 application images except for the Phase 6 classifier.
Extra health checks used HTTP for MLflow/collector/API/dashboard and infrastructure
socket checks for assembler/critic/healer; these are validation probes, not new
application health endpoints.

**Full startup failed.** The available collector image lacks `google.protobuf`,
needed by the current OTLP import, and logged
`ModuleNotFoundError: No module named 'google'`. It restarted **9** times.
The attempt was stopped while fresh PostgreSQL was still initializing; no
healthy-startup time exists. An attempted current collector build with
`--network none --pull=false` failed because `hatchling` was not available
offline. BuildKit still performed Docker Hub metadata/auth lookups despite
that flag, so the strict **no-external-API constraint also failed**. No
LLM/provider request occurred. No alternative image was counted as a full-stack pass.

The full synthetic HTTP/Kafka count check, actual critic-group zero-lag check,
and five-minute critic/healer idle hold were **not run**. No traces were sent
to the full collector; no topics or offsets were changed. Critic/healer were
never created or started. Their requested runtime log/cost-ledger comparison
therefore has no result; it must not be described as a passing idle hold.

The independent **classifier fail-loud check passed** using the Phase 6 image.
Empty tmpfs mounts hid `/app/cross-encoder`, `/app/sentence-transformers` and
the Hugging Face cache, without deleting models. `/health` returned **503**,
`nli_ready=false`, `consumer_running=false`, and an explicit required-NLI
offline-load error. Logs contained one startup/consumer refusal and no consumer
start. The throwaway container had no network and was stopped/removed.
Two setup probes preceded this result: the first sampled initial readiness too
early; the second hid only the HF cache, leaving the locally baked model visible.
Neither was counted as a fail-loud pass.

**Lite startup/hold/trace checks passed, with a host-ingress limitation.** Project
`nexus-lite` used image `nexus-phase6-nexus-lite:check` and a fresh named volume.
Observed time from `up -d` invocation to confirmed healthy was
**20.188 seconds**. The zero-traffic hold lasted
**300.000 seconds**, with
**39 healthy observations** and zero automatic
restarts. The host port then refused an HTTP connection on the internal network.
Cleanup stopped the container; it was explicitly started again using the same
untouched volume to test HTTP via container loopback. That request accepted all
four fictional spans and produced one persisted trace, one `LOOP_DETECTED`
alert, and one `generic_fallback_no_llm` proposal. It was stopped again. The
separate explicit start/stop is recorded; the idle hold itself had no restarts.
Host ingress has not passed. No LLM/provider code is called by the lite worker.

Peak RAM below comes from `docker stats --no-stream` sampling. CLI-rounded MiB
values were converted to bytes in the JSON. Full figures cover **only five
services during failed startup**, not a healthy full stack; missing observations
are not zero. Sampling paused three seconds between CLI calls.

| Container/service | Observed peak MiB | Docker restart count |
| --- | ---: | ---: |
| Full attempt: kafka | 322.90 | 0 |
| Full attempt: postgres | 89.98 | 0 |
| Full attempt: redis | 13.10 | 0 |
| Full attempt: mlflow | 497.10 | 0 |
| Full attempt: nexus-collector | 2.30 | 9 |
| Full attempt: nexus-assembler | not measured | 0 |
| Full attempt: nexus-classifier | not measured | 0 |
| Full attempt: nexus-api | not measured | 0 |
| Full attempt: nexus-dashboard | not measured | 0 |
| Full attempt: nexus-critic | not measured | not started |
| Full attempt: nexus-healer | not measured | not started |
| Lite: nexus-lite | 66.15 | 0 |

The sum of the five observed full-service peaks was
**925.38 MiB**; the largest concurrently sampled total was
**920.55 MiB** across
**13 samples**. Neither is a full-stack RAM total. Lite's observed
peak/total was **66.15 MiB**
across **43 samples**, including the trace check.

Host RAM was **33986535424 bytes**, with
**32 logical processors**.
Docker **28.5.1** exposed
**10424061952 bytes** and
**32 CPUs**. The inspected WSL configuration
specified `memory=10GB`, `swap=8GB`, `autoMemoryReclaim=gradual`.
Full-attempt containers had Docker memory and NanoCPU limits of zero (no
individual cap; the Docker VM limit still applies).

All original container IDs and volume names remain present. Failed-attempt
containers and volumes were retained; no original data was deleted. Final
inspection found no running Phase 5, Phase 6, or lite containers. Local raw
evidence and sampling records remain under ignored
`data/phase6/runs/scratch/stack-61c/`; their hashes are in the committed JSON.
The new hand-written test fixture is
`scripts/phase6/fixtures/fictional_loop.json`; it contains no NexusBench data.
TEST remained sealed and no ntfy notification was sent.

The next full attempt needs a current collector image with its declared OTLP
dependencies already installed, and an egress guard that also prevents registry
lookups. Then repeat the full startup, synthetic suppression, critic-offset
boundary, five-minute idle, and complete RAM measurements. CI checks for the
result commit are linked from
[draft PR 5](https://github.com/sankalp-rajeev/Nexus/pull/5/checks); the handoff
records the actual run URL after the single push.
