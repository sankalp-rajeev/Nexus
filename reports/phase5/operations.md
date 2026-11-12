# Phase 5 run operations

Run these commands from `C:\Umich\Projects\nexus-phase5` on `phase-5-perf`.
The registration, manifest and runner must match the new `phase5-prereg` commit.

Launch, or resume after a dead controller:

```powershell
.venv\Scripts\python.exe -m scripts.phase5.run --detach
```

This uses the fixed concurrency 2 and both caps in `run_config.json`. The PID and
exact child command are saved in `data/phase5/runs/runner.pid.json`. Check that
the old controller is dead before resuming; `runner.lock` prevents two controllers
from processing the sample simultaneously. Completed occurrence IDs are skipped.
Do not remove the budget database, locks, manifest, completed records or caches
to resume: prior smoke/run spend remains counted against ledger $9 and provider $4.

Read both spends, cap state, PID and recent progress without outcome analysis:

```powershell
.venv\Scripts\python.exe -m scripts.phase5.status
```

Watch progress:

```powershell
Get-Content data\phase5\runs\heals.log -Tail 10 -Wait
```

Read controller diagnostics if needed:

```powershell
Get-Content data\phase5\runs\runner.stdout.log -Tail 30
```

Each heal's terminal result is an atomic JSON file under the ignored
`data/phase5/runs/records/`. Each actual API attempt is durably reserved/settled
in `data/phase5/runs/budget.sqlite3`, including WAL state. Unknown calls retain
conservative reservations against both caps. `status.py` distinguishes known
provider actual spend from its reserved/accounted total. At a cap stop the log
states `stopped: cap reached`; the database records the triggering cap.

No raw runs, logs, JSONL or patch files are committed. The only smoke outputs
committed are the selected patch/gate summaries under `reports/phase5/smoke/`.
The 100-heal gate decisions are descriptive; latency and cost are the Phase 5
endpoints. No L3, L4 or Gemini execution is part of this command.
