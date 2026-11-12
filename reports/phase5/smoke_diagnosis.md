# Phase 5 stopped at the smoke comparison

The overnight run was **not launched**. Per the requested stop rule, no
pre-registration, sample manifest, commit, push, or `phase5-prereg` tag was made.
All changes remain in the Phase 5 worktree for review. L3, L4 and Gemini were not run.

## Smoke comparison

Outcome means the frozen A1 own-task safe-repair majority over seeds 0, 1, 2.
The class column is the detector prediction supplied to the critic; both current
critics also independently diagnosed that same class.

| DEV item | Phase 4 gate | Fresh gate | Failure class, old / fresh | Repair outcome, old / fresh | Seconds |
|---|---|---|---|---|---:|
| `nb-6dbb58488330a80f` (`qa-003`) | promoted | promoted | HALLUCINATION / HALLUCINATION | true / true | 433.938 |
| `nb-fb4b825f6e52387e` (`tool-020`) | rejected | **promoted** | TOOL_MISFIRE / TOOL_MISFIRE | true / true | 441.998 |

The second item's old patch broke seven regression tasks; the fresh patch broke
zero. Both repaired the own task on all three seeds and had held-out pass rate
1.0 versus the fixed no-patch reference rate 0.2. Thus only gate check 3 flipped.

## Diagnosis

Both smoke items produced fresh patch text and a different patch hash from Phase
4. For the mismatching item, the old patch hash is
`611c98e2b0a409e807587f8d41934a96b63481307bd4667681d539396b555da8`;
the new hash is
`928f7f5245db692aa0a572959027ba843c86801e40e631306a4ff3b82a4b40a5`.

The old proposal constrained `get_order` IDs to `B-####` and changed general
argument/error handling. The fresh proposal uses an uppercase-letter/hyphen/digits
format and a different, more specific validation/error-recovery instruction.
Those are generated proposal outputs, not changes to the frozen critic prompts.
The differing instructions coincide with the regression outcome change; this
diagnosis does not attribute the entire difference to one instruction without
additional experiments.

The offline diagnostic confirmed, for **both** smoke items:

- The canonical DEV detector-view SHA-256 matches the Phase 4 continuation record.
- The evidence packet, baseline deployment config and prompt-template hashes match.
- The reported model fingerprint matches: `bc19ba97cbe016479903222bb1578db6`.
- The unchanged frozen scorer reproduces the old gate from old saved executions.
- The same scorer, called directly without the measurement wrapper, reproduces
  the fresh gate from the fresh saved executions and identical baseline references.

This supports **critic regeneration variability at temperature 0.2**, rather
than a measurement/infra decision change. It is not the known confirmation-seed
noise test: here the proposed patch itself changed before gate execution. No
extra paid replay was performed to force agreement.

Full checks and hashes are in `smoke_diagnosis.json`; the reproducible read-only
diagnostic is `scripts/phase5/diagnose_smoke.py`. The critic infra entrypoint is
not used by the in-process benchmark pipeline.

## Timing, spend and run state

The two-heal mean projects **12.166 hours for 100 heals at concurrency 1**.
Concurrency 2 would project **6.083 hours** and would be the smallest integer
concurrency meeting nine hours. This is a smoke planning estimate only; no
concurrency or finish time was registered for a run that did not launch.

Final shared ledger spend is **$0.15867720** across **693 settled API attempts**,
with **zero API errors, timeouts or unknown reservations**. These are smoke
measurements only; no overnight results exist.

The exact executed smoke command was:

```powershell
.venv/Scripts/python.exe -m scripts.phase5.run --smoke *> data/phase5/runs/smoke.stdout.log
```

It exited after the comparison with the expected STOP error. There is no
overnight process ID, launch command, first-three-heal log, or resume operation
to report. Do not rerun or resume a paid experiment without resolving the smoke
stop rule. The local `smoke.log` has these two completion lines:

```text
id=smoke-promoted decision=promoted seconds=433.938 running_spend=$0.073600 status=ok
id=smoke-rejected decision=promoted seconds=441.998 running_spend=$0.158677 status=ok
```

The final frozen check still passes with an empty Git diff and normalized-content
match. All 344 pre-smoke provenance/hash comparisons passed; see
`hash_comparison.csv` and `raw_byte_inventory.md`. The full 11-service stack passed
the 300-second zero-restart watch; cause/fix and changed infrastructure paths are
documented in `infra_notes.md` and `validation.md`.

Final offline validation: **432 passed, 10 explicitly skipped**, including 14
passing measurement/controller tests; lint passes. Skips preserve the sealed TEST
artifacts and the existing auxiliary-file exclusion. No additional paid calls
were made during diagnosis or final validation.
