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
