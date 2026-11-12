# Frozen-file reads and Phase 4 hash compatibility

The revised check passes with an empty Git diff and identical frozen content
after CRLF-to-LF normalization. Checkout line endings and Git settings were not
changed. `hash_audit.json` contains all 344 comparisons: all match. This includes
114 prompt-provenance entries and both intended/applied config hashes for 109
distinct configurations across 17,952 DEV execution records. The adjacent CSV
provides the requested name / Phase 4 recorded / now / match table in full.

## Frozen sources consumed as bytes

- `services/critic/round3_part_b.py:259`: hashes the working
  `bench/detector_view.py` using `read_bytes()`. Recorded and current raw hashes
  both start `5cfb3be3cc06`; the CRLF version reproduces the recorded hash.
- `services/critic/round2_legacy.py:17-19,25-34`: `git_source()` returns raw
  pinned Git blobs for the original graph, validator, fallback and both prompts;
  `OriginalCritic` hashes those blobs. Its on-disk prompt check already normalizes
  CRLF before comparison. Hashing the current graph as a substitute would be
  incorrect: the runtime intentionally hashes the pinned historical graph.
- `services/critic/arms.py:11-17`: loads the two original prompt Git blobs and
  hashes those bytes for `v1_structured` provenance. Both recorded prompt hashes
  match; working prompt bytes normalize to the pinned content.
- `services/critic/phase4_handoff.py:44-46,97-105,142-158`: reads pinned Phase 4
  `bench/heal/config.py` and `critic.py` contracts through raw `git show`, and hashes
  these bytes plus preregistration/label blobs. These are Git-blob hashes, not
  raw working-tree-file hashes. Every recorded value matches that same runtime
  calculation; the LF working-source representation reproduces the loader hashes.
- `bench/heal/test_phase.py:109-110` hashes the thresholds JSON using `open(...,
  "rb")`. This is a sealed TEST-only evidence-generation path: inspected as code
  only, never imported or invoked, and its sealed evidence/results were not opened.

## Raw reads of inputs and saved artifacts (not frozen source code)

- `bench/heal/sets.py:83-85`: `file_sha256()` hashes the entire labels file in
  binary mode. Its DEV preregistration hash matches. Only the explicitly requested
  opaque-byte digest was computed; no TEST row was decoded for this audit.
- `services/critic/dev_adapter.py:70`: reads trace lines as bytes, allowing only
  whitelisted DEV IDs to reach deserialization. It does not hash source files.
- `services/critic/round3_part_b.py:258`: hashes the DEV prediction JSON bytes;
  the recorded/current raw values match (CRLF reproduces the recorded hash).
- `services/critic/phase4_handoff.py:191`: hashes preserved saved round-3 artifact
  bytes during migration, rather than frozen source. No migration was run.
- `services/critic/proxy_sample.py:41` and `round3_audit.py:66-67,78`: hash saved
  round-2 proposal artifacts and review sheet/key bytes. These offline historical
  audits are not executed in Phase 5 and do not read frozen source as bytes.

## Content hashes, not raw-file hashes

- `bench/heal/config.py:45-50,74-75,138-149` hashes canonical JSON of config
  values and patch operations. `bench/heal/agent.py:49-55` hashes the effective
  prompt, step budget and tool specs; `harness.py:94,208,221` and `score.py:76`
  compare these identities. The audit called these unchanged runtime functions
  against every saved DEV patch/config, with zero mismatches or missing patches.
- `services/critic/registry.py` reads no files and computes no digest: it copies
  the explicit config and applies validated replacements in memory.
- `services/critic/fault_reversal.py:48` hashes serialized leaf values for scoring.
  `leak_assert.py:40` hashes serialized detector views, not source-file bytes.
- `bench/detector_view.py:62,66`, `bench/heal/harness.py:88`, `bench/llm.py:163`,
  and `services/classifier/features.py:17` hash IDs, requests or feature payloads.
  These do not hash source file bytes. Python-loaded string constants use normal
  source newline handling; the saved effective-config matches verify compatibility.

The new Phase 5 verification scripts are also raw-byte readers:
`scripts/phase5/check_frozen.py` reads each protected file and normalizes CRLF
only for its content comparison; `audit_hashes.py` reads the explicitly listed
provenance inputs and recomputes the original Git-blob/runtime hashes. Neither
is part of a detector, prompt, registry, gate or outcome decision.

Only DEV records were inspected. `results/heal_runs.jsonl` is the documented DEV
store; the separate TEST store and `reports/phase4/test/` remained sealed.
