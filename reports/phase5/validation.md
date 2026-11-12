# Phase 5 setup validation

Worktree: `C:/Umich/Projects/nexus-phase5`; branch: `phase-5-perf`.
Starting HEAD and origin/main both resolve to
`81289ed95be6a16327929ff8dca34001f1079e6b`.
The scored reference is `phase4-test-scored` at
`2386cfa3e7b835b0c976bef4f9a4cfd795a35493`.

## Freeze and hash checks

`python scripts/phase5/check_frozen.py` passes. The requested frozen-path Git
diff is empty; every frozen file matches after CRLF-to-LF normalization.
Raw CRLF-only differences print as INFO. No frozen logic, checkout line endings,
`.gitattributes`, or Git configuration was changed. The critic Dockerfile is an
explicit infrastructure exception to the frozen-path list.

The offline hash audit passes all **344 comparisons**: 12 file/pinned-source
hashes, 114 prompt-provenance hashes, and 218 intended/applied config hashes for
109 distinct configurations. All **17,952 DEV run records** were covered, with
zero missing patches. See `hash_comparison.csv` for the full requested table,
`hash_audit.json` for runtime methods and alternate LF/CRLF digests, and
`raw_byte_inventory.md` for every relevant raw-file consumer.

## Stack

All 11 isolated Phase 5 services stayed healthy for **300 seconds with zero
restarts**. The watch records container names, start times, health and restart
counts every 30 seconds in the ignored local
`data/phase5/runs/stack_stability.json`. `stack_ps.txt` records Compose status.
The existing Nexus stack and its PostgreSQL volume were not modified.
The critic restart cause/fix is recorded in the five-line `infra_notes.md`.

## Tests

Final guarded suite: **435 passed, 10 skipped**, no failures. All five live Kafka
integration tests passed using the external listener on localhost:29092.

The skips are explicit: nine checks would open sealed TEST data/results or
regenerate a report from those results; one existing provenance check skips an
auxiliary DEV prediction file. `pytest_dev_only.py` blocks sealed artifact opens
and substitutes the existing DEV-only streaming adapter for the legacy CSV
reader during tests only. Production/frozen source remains unchanged.

The 17 new measurement/controller tests all pass. They verify unchanged actor
and critic HTTP payloads/return values, identical promoted/rejected gate outputs
from the frozen scorer, monotonic stage/error timing, cache token accounting,
peak/off-peak prices, persistent unknown-call reservations, concurrency-safe
ledger caps, atomic completion/resume identity, and idempotent progress logs.
They also block credentials in request bodies and any non-approved API destination.

Commands (all temporary state stays under the ignored run directory):

```powershell
$env:KAFKA_BOOTSTRAP_SERVERS='localhost:29092'
$env:POSTGRES_HOST='127.0.0.1'
$env:POSTGRES_PORT='55433'
$env:REDIS_HOST='127.0.0.1'
$env:SLACK_WEBHOOK_URL=''
.venv/Scripts/python.exe scripts/phase5/pytest_dev_only.py -p no:cacheprovider -q --basetemp=data/phase5/runs/pytest-final
.venv/Scripts/python.exe -m pytest -p no:deepeval tests/unit/phase5 -q --basetemp=data/phase5/runs/pytest-measurement-5
.venv/Scripts/python.exe -m ruff check scripts/phase5 tests/unit/phase5 infra/entrypoints/critic.py infra/phase5_health.py
```

The guarded runner always passes `-p no:deepeval` to pytest.

## Measurement semantics

The wrapper calls the existing frozen detector, classifier precedence, selected
`v1_structured` critic, Phase 4 config adapter, configured agent and scorer. It
changes no model request parameters. Actor temperature is 0, critic temperature
is 0.2. Request routing, proxy/TLS configuration and connection pools are retained.

Monotonic stage timings include detection, classification, critic calls and each
gate task batch plus its existing per-task outcome calculations. Total also
includes loading/configuration and final gate-decision overhead. Start/end ISO
timestamps carry the America/New_York offset. Skipped stages are marked explicitly.

No patched Phase 4 execution result is reused. The gate uses the same fixed
Phase 4 seed-0..2 no-patch references where available; any missing reference is
executed and timed. Every patched evaluation is fresh within its heal's new
local cache. Provider-side caching remains enabled and is measured from API usage.

The ledger prices all reported input at $0.30/M and output at $1.20/M. The second
cost view applies published cache-hit/miss and time-of-day prices to API-reported
tokens; it is a usage-derived cost estimate, not a provider invoice. Missing
cache usage remains unknown. Current rates and UTC peak windows were checked at
https://api-docs.deepseek.com/quick_start/pricing/ on 2026-11-11. The planned run
does not overlap a Chinese public holiday.

The user amended and accepted the smoke protocol before registration. The shared
caps are now $9 ledger and $4 provider-reported usage-priced actual cost, both
including smoke calls and every actual retry attempt. SQLite transactions reserve
a conservative byte-bounded cost against both caps before sending a request.
Unknown/interrupted attempts keep their full reservation. Completed heal records
are atomic JSON files, protected by occurrence-ID locks; restarts skip them.
Incomplete heals restart in a new attempt directory and their previous API spend
remains charged. Terminal errors/timeouts remain explicit sample records.

The amendment tests verify that concurrent calls cannot exceed the provider cap,
unknown provider usage remains reserved on restart, and legacy smoke ledger and
provider amounts survive the cap migration. A local-only process probe confirmed
Windows accepts the runner's detached/new-process-group/breakaway-from-job flags.
See `preregistration.md` for the accepted smoke table, descriptive-only gate policy,
fixed concurrency 2 and full run protocol.
