# TRAIL pre-registration amendment A2

A2 is registered on 2026-11-13, before external scoring code exists or external detectors have run. It prospectively divides the 127 label-join-eligible external traces into two version-specific evaluation cohorts. Original pre-registration `8bc721b` and amendment A1 `8222003` otherwise remain unchanged.

**TRAIL-A is scored now, once, with the frozen v1 detectors. TRAIL-B is sealed for a future v2 detector version, to be scored once after v2 is frozen; nothing in this run reads TRAIL-B labels or runs detectors on TRAIL-B.**

No TRAIL-B trace content is loaded by this evaluation either. The partition procedure reads only the original committed test-ID lists and the six committed exclusion IDs. It does not open dataset rows, labels, annotations, or detector outputs. The earlier interrupted part 2 request performed only its requested pre-flight join-key audit; no external scoring code existed and no external detector execution occurred before A2.

## Fixed selection and manifests

Seed: **20261114**. From each original source split, remove the six pre-registered GAIA exclusion IDs, sort the remaining IDs, and use one Python `random.Random(20261114)` instance while iterating sorted source names. Select `ceil(n/2)` IDs for TRAIL-A; the complement is TRAIL-B. Write combined cohort ID lists sorted and LF-terminated. No resampling is permitted.

| Source | Eligible before A2 | TRAIL-A | TRAIL-B |
| --- | ---: | ---: | ---: |
| gaia | 99 | 50 | 49 |
| swe_bench | 28 | 14 | 14 |
| Total | 127 | 64 | 63 |

The 15 dev traces remain outside both cohorts. The six original GAIA label-join exclusions remain outside both cohorts; their IDs and reasons are unchanged in the original manifest and A1. Future v2 validation on B must not use B for adaptation, threshold selection, or exploratory detector execution before v2 is frozen.

Dataset revision remains **b424ce63d5973d5dcd7169b1bc3c07ccdee276d1**. The original manifest SHA-256 remains `4081a888f8d624b257cc8a6fe1648a0709160b05154bfd5df59967bf6c16f061`.

The new [ID-only manifest](trail_split/a2/manifest.json) and [SHA-256 manifest](trail_split/a2/manifest.sha256) bind the two new ID lists and the selection rule:

- [TRAIL-A IDs](trail_split/a2/trail_a.txt): `1b1c8afba707315f519735f7bb52e8f63ae4d0922334a9f46728688b641346bf`.
- [TRAIL-B IDs](trail_split/a2/trail_b.txt): `7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f`.

`scripts/external/partition_trail_a2.py` reproduces the allocation using IDs only. A synthetic test verifies stratification, disjointness, deterministic selection, exclusions, and refusal to overwrite a changed partition. Git attributes preserve LF under `reports/external/trail_split/`.

## Evaluation boundary

All part 2 references to test data now mean **TRAIL-A only (64 traces)**. Report the original 133-trace test pool, six pre-registered label-join exclusions, the 63 reserved B traces, and the 64-trace A evaluation denominator separately. HALLUCINATION applicability/abstentions are measured within A only, per A1; they do not alter cohort membership. PLAN_DRIFT and CONTEXT_BLEED are not scored.

To avoid loading B rows from the shared parquet files, stage only A's individual trace and processed-annotation JSON files from the same immutable dataset revision before scoring. They remain under excluded `data/external/trail/`. File paths are constructed solely from the committed A IDs and original source membership. No B files are downloaded, opened, decoded, scanned, or passed to detectors. The scorer accepts only this A-specific private directory, verifies exact A file membership and trace-ID label joins, and never opens the combined parquet files. Dataset staging precedes the offline scoring run and does not fetch models.

Before execution, verify the original and A2 committed manifests, the original six exclusion IDs, the pinned on-disk dataset revision, the empty adapter/detector-path diff against `8222003`, and the exact local model cache. The scoring code and synthetic metric tests will be committed before the first A detector invocation. A durable private run marker prevents an accidental second completed run. A crash-only retry must be explicitly recorded; no changes for better metrics, no post-result exclusions, and no adapter, threshold, taxonomy, or retrieval-rule changes are permitted.

Results stay on `external-validation`. No raw gated content, prompts, outputs, annotation descriptions, or demo changes are published. Only code, protocols, aggregate numbers, and authorized trace IDs/manifests are committed. No provider calls, container commands, subsystem commands, model downloads, frozen-file changes, or NexusBench TEST access are used.

**frozen detectors, thresholds unchanged, scored once, reported as is**
