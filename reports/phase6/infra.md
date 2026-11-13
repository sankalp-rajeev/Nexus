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


## Attempt 1: failed — 2026-11-12 (step 6.1c)

Measured on 2026-11-12 (America/New_York), checkout
`a18b0b8cf8755b74a21d4d785a9cb26f6e7f0686`. The original machine-readable
results are preserved in commit `5779aac054164f247145af1ccb2b3737144688e4`
at `results/phase6/stack_validation.json`. Overall validation **did not pass**.
No application, frozen code, existing fixture, CI workflow or test runner changed.

This dated section preserves attempt 1. Its two setup mistakes were a stale
collector image and an overly strict network rule. Step 6.1d explicitly permits
image/package/model downloads and GitHub operations; its policy supersedes the
old registry-lookup prohibition discussed below. The current JSON is reserved
for the passing attempt 2 rather than the failed historical measurements.

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


## Attempt 2: passed — 2026-11-12 (step 6.1d)

The clarified policy allows Docker/package/Hugging Face downloads and GitHub
operations. It prohibits sending project data, traces or provider keys to a
third party. Application startup/idle paths were re-read before work and their
hashes match the prior audit. Critic/healer make no provider call at startup
or while idle. TEST remained sealed; no ntfy notification was sent.

### Lite ingress root cause, fix and regression

The failed override used an **internal-only Docker bridge**. The old container
already had Uvicorn bound to `0.0.0.0:8000` and configured host mapping
`127.0.0.1:18000 -> 8000`. With only the internal network, container-loopback
health returned 200 while host HTTP was refused. Attaching an ordinary bridge
live still did not establish host-port forwarding. A cold start with that
bridge already attached returned host HTTP 200 with the same image, application
and port configuration. Stop/start in attempt 1 had retained the internal-only
network, so it had never fixed host ingress; the request was merely moved to
loopback. The cause was the validation network, not Uvicorn binding or readiness.

`docker-compose.lite.yml` now explicitly selects an ordinary bridge with
`internal: false`. The full validation override also uses a normal bridge.
Runtime validation clears provider keys/webhooks, disables telemetry and keeps
models offline. The new standalone regression script
`scripts/phase6/check_lite_host_ingress.py` cold-starts a unique service and
fresh volume, asserts host GET/POST success on documented port **18000**, checks
the deterministic result, and requires unchanged `StartedAt` and restart count
zero through the POST. Its initial control passed in
**13.797 s**, using the existing lite image, without
a restart. It then ran again with the rebuilt image and the full hold below.
Every created container and volume is retained; the script only calls `stop`.

### Rebuilt images and provenance

`docker compose build` rebuilt all seven full application images and the lite
image from clean application source at
`5779aac054164f247145af1ccb2b3737144688e4`. Each image carries that exact
`org.opencontainers.image.revision` label. Normal build-cache reuse was allowed;
no stale application image or source bind mount was used in the measured run.
The network declaration and new validation script are working-tree changes
outside application image COPY inputs. The collector import probe passed with
`google.protobuf 6.33.6` and the
collector application import, on network `none`, exit code 0.

- `nexus-api`: `sha256:bb248fa210b89e716f65cbbdcc0f86e336232f0001f59b43e2fce1d6ef83f9ab`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-assembler`: `sha256:2e9fec7302dd3185a4182acedd354deb130135a22871b55f9197fcf3192a8be7`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-classifier`: `sha256:4da7336c4b60378aaeea47d9d0239b70ca10a4669aec22b188776b8c78e19226`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-collector`: `sha256:4584c4b5fa5bfcf6763ea0f75817ddb047786164b4d9a22ebacbe42846a7b431`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-critic`: `sha256:a573da7623a082344638116dbd7774437924f124d551548a69e02913764e893a`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-dashboard`: `sha256:c447aa73f56b70b2ef096cb0a9a9af6343feec5fc19f31d2658851e4d6e3f3f4`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-healer`: `sha256:c9abb701216a7efebbbf7076755346b68fcbb366c279bd4fd214f31a3a574bdb`, commit `5779aac054164f247145af1ccb2b3737144688e4`.
- `nexus-lite`: `sha256:34d4b4bbfe17d119c450a790a403adf38bb3219b38e4c3901b7797894090fb15`, commit `5779aac054164f247145af1ccb2b3737144688e4`.

Kafka, PostgreSQL, Redis and MLflow are upstream image services without local
build definitions. Their exact local IDs and registry digests are recorded in
the JSON; they are not represented as built from a Nexus commit.

### Measured checks in order

1. **PASS — full startup:** project `nexus-phase6`, new service identities and
   fresh PostgreSQL/MLflow/Kafka state; Phase 5 remained stopped. From `up -d`
   invocation until all nine services except critic/healer were healthy:
   **75.531 s**. Critic/healer were absent during this stage.
2. **PASS — synthetic boundary:** host HTTP accepted two batches of four
   hand-written fictional spans. One batch had boolean `nexus.synthetic=true`
   on every span; the other removed only that marker and used distinct IDs.
   Kafka console consumers read **2 LOOP_DETECTED classification records**
   and **exactly 1 alert**, for the unmarked trace. Classifier health reported
   **synthetic_suppressed=1**. Console-consumer timeout after the expected
   records is the intentional end-of-observation timeout, not a pipeline error.
3. **PASS — actual critic boundary:** with critic/healer still absent, reset
   the actual `nexus-critic` group to current log end, without deleting data.
   Current offset **1**, log end
   **1**, lag
   **0**; healer pending patches **0**.
4. **PASS — full idle:** only after that boundary, start critic/healer and
   wait for all eleven health checks. Their observed startup increment was
   **11.828 s**. Hold with no trace traffic for
   **300.000 s**. All eleven remained healthy, every
   restart count stayed **0**, and each `StartedAt` stayed unchanged. Critic
   health checks retained a Kafka admin client and verified active group
   membership; other worker checks verified their local dependencies. Docker
   stats/health sampling ran throughout the hold.
5. **PASS — provider evidence:** critic/healer logs contain **0 processing,
   provider-request or error events**. Critic's cost ledger before/after:
   **exists=False,
   bytes=0,
   rows=0**, unchanged. Its hash/existence
   snapshot and the host cost-ledger snapshot match before/after. After the
   hold, critic lag was **0** and the patch table still contained **0 rows**.
   There were **0 observed provider calls**. Startup/idle source auditing
   confirms the provider paths require work that was absent.
6. **PASS — stop full:** Compose `stop`, never `down -v`; all containers and
   volumes retained.
7. **PASS — lite cold start and host ingress:** project `nexus-lite`, another
   fresh named volume and unique service, rebuilt lite image. Time to Docker
   healthy plus host HTTP 200: **13.657 s**. Idle hold:
   **300.000 s**, healthy throughout with restart count
   **0**. Then a fictional trace sent **from the host** received HTTP
   **202**, accepted **4** spans and
   produced **1** persisted trace, **1 LOOP_DETECTED** alert and
   **1 generic_fallback_no_llm** proposal. Host health reported four received
   spans. `StartedAt` stayed unchanged through the POST; no manual or automatic
   restart/stop-start workaround occurred. Lite was stopped afterward.

The classifier fail-loud result from attempt 1 is carried forward as already
passed, and **was not repeated**, as requested.

### Sampled peak RAM and restart counts

| Container/service | Image ID (short) | Peak MiB | Restarts |
| --- | --- | ---: | ---: |
| Full: kafka | 41c20d65b0a2 | 400.80 | 0 |
| Full: postgres | 6343bdc87ca1 | 124.50 | 0 |
| Full: redis | 2e3eb11462c4 | 7.66 | 0 |
| Full: mlflow | 47c5c26d06a4 | 454.70 | 0 |
| Full: nexus-collector | 4584c4b5fa5b | 44.31 | 0 |
| Full: nexus-assembler | 2e9fec7302dd | 36.88 | 0 |
| Full: nexus-classifier | 4da7336c4b60 | 383.50 | 0 |
| Full: nexus-critic | a573da7623a0 | 32.31 | 0 |
| Full: nexus-healer | c9abb701216a | 38.45 | 0 |
| Full: nexus-api | bb248fa210b8 | 47.04 | 0 |
| Full: nexus-dashboard | c447aa73f56b | 28.13 | 0 |
| Lite: nexus-lite | 34d4b4bbfe17 | 48.26 | 0 |

Full sum of individual service peaks: **1598.28 MiB**.
Full peak concurrent sampled total: **1502.65 MiB**,
across **75 samples**. Lite peak/total:
**48.26 MiB**, across
**65 samples**. These are `docker stats --no-stream`
observations, not continuous process-RSS maxima. Sampling paused three seconds
between CLI calls; rounded CLI memory units were converted to bytes in JSON.
Full peaks include startup and the Kafka console tools used for the synthetic
check. The JSON also separates idle-only samples: sum of idle service peaks
**1525.04 MiB**, peak concurrent idle
total **1494.78 MiB**, across
**54 samples**.

Host physical RAM: **33986535424 bytes**;
logical processors: **32**.
Docker **28.5.1** exposed
**10424061952 bytes** and **32 CPUs**.
Re-read WSL settings: `memory=10GB`, `swap=8GB`, `autoMemoryReclaim=gradual`.
Per-container memory/NanoCPU limits were zero (no individual cap; VM cap applies).

### Evidence and preserved setup runs

Two validation-probe setup runs preceded the passing measurement: one gave the
classifier a PostgreSQL probe despite its real HTTP readiness being healthy;
the other discarded a temporary Kafka admin client before its asynchronous
critic-membership result completed. Those harness probes were corrected and
verified directly; neither setup idle result is counted as passing. Their
containers, volumes, traces, logs and partial measurements remain in scratch.
The second setup's synthetic/offset checks passed, and its actor logs showed
only idle startup, with no processing/provider activity.

All original container IDs and volume names were verified still present.
Phase 5, full and lite projects were verified non-running at completion. No
data was deleted. Raw evidence lives under ignored
`data/phase6/runs/scratch/stack-61d/`; the committed passing JSON includes
evidence hashes, full image IDs, source commits, exact Kafka records, before/
after ledger evidence, RAM aggregates, and final checks. The original attempt
1 remains above and in commit `5779aac`.

No `.github/`, existing conftest/fixture or DEV-only pytest runner changed.
The new infrastructure regression is a standalone script; no benchmark split
or pytest collection was invoked. The handoff includes the commit-specific CI
run link without waiting for CI.
