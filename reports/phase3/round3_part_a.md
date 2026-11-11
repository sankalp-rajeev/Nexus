# Phase 3 round 3, part A

Code and saved-output sampling only. No generation, task replay, detector inference,
Docker, rebase, branch checkout, merge, push, or tag operation was performed.
Only `services/critic/`, `tests/unit/critic/`, and `reports/phase3/` were edited.

Phase 2 was read with fetch/show at `5db12262b742e8b5aa7fce771631330d430260c9`.
Contracts inspected: `bench/detector_view.py`, `services/detectors/{pipeline,common,
rules,bleed,drift,hallucination}.py`, the DEV prediction JSON, labeler and benchmark
revision notes. No TEST dataset, labels, manifest, or prediction payload was read.

## Arms and provenance

`run_critic(..., config={"critic_arm": "new"})` and
`run_critic(..., config={"critic_arm": "v1_structured"})` select the arms.
The service also accepts `CRITIC_ARM=new|v1_structured`; explicit config wins.
Invalid arms fail validation. Every new proposal, including rejected proposals
and fallbacks, persists `critic_arm`.

The `v1-prompt-structured` arm loads both original prompt files from
`phase-1-nexusbench` using `git show`, preserves their original content in rendered
`original_prompt` fields, and records their SHA-256 hashes. It makes a structured
diagnosis call, then a structured patch call. The common wrapper supplies the
view, evidence, registry snapshot, schema and replacement rules. Original response
format instructions are overridden by the explicit transport contract. Thus this
preserves original prompt content, not an identical wire prompt or call count to
the new critic. Original source files are never checked out or imported over the
current implementation.

Both structured arms use the same validator, registry, replacement-only dry run,
rejection/audit boundary, retry limit, and provenance aggregation. Diagnosis calls
are included in tokens, cost and latency. Strict schemas inline references and
require nullable diagnosis/citation fields. DeepSeek, Gemini, Ollama and the
explicit unit mock support structured diagnosis. New prompt version:
`critic-round3-v1`; original-content arm: `v1-prompt-structured`.

## Detector boundary

`from_detector(prediction, view)` accepts only Phase 2's `pred` field and an opaque
`bench.detector_view` trace. It never imports the labeler, world registry, injector,
filesystem, or scorer. Metadata is projected through a deployment-visible allowlist;
the neighboring `label_v1`, model fields, ownership/session annotations, task/family,
gold answers and injection config are never traversed or serialized. Part B passes
the projected view as the full critic trace, including for the original critic.

Phase 2's saved DEV outputs have trace-level predictions, not span attributions.
The adapter records this explicitly: locations are deterministic candidates, with
a tagged last-span fallback if necessary. They are not ground truth. `NORMAL`
returns no evidence and causes no critic call. The oracle builder now requires
`allow_oracle=True`; historical oracle runners pass that flag explicitly.

The leak regression test plants tripwires for every labels.csv column and known
injection-only fields, forbids their reads/copies/serialization and filesystem IO,
and checks adapter imports. All fixtures are handmade.

## C3 scoring

`score_c3` is scoring only. It reports exact `proposal_type_match` against ground
truth, plus independent diagnosis `type_match` and diagnosis coverage. The proposal
envelope inherits the detector label; it is never credited as an independent model
diagnosis. The unchanged original prompt does not request an independent class
field, so that supplemental coverage may be absent for the original arm.

Citation scoring accepts explicit structured span IDs or zero-based indices into
`trace.spans`, or explicit legacy `FAILURE_SPAN_ID` / `FAILURE_STEP` lines. It uses
exact equality, rejects conflicting, ambiguous and out-of-range citations, and does
not infer citations from incidental mentions. Missing citations fail. Fallbacks
cannot count as correct diagnoses. Unknown truth locations are excluded from the
location denominator and counted separately.

The DEV scoring-only truth builder locates the third successful repeated call for
loop, original error for misfire, first foreign read for bleed, first executed
injected-ID call for drift, and final-answer root span for hallucination. These are
operational fault-origin conventions, not causal proof about the initial prompt.
Only this scorer may access raw ownership/injection information; it runs after the
proposal returns. Summaries include all five classes and a separate detector-wrong
population, also by class, including detector misses.

## Human specificity check

`proxy_sample.md` contains exactly 20 saved round-2 proposals with patch text,
evidence and blank human-verdict cells. Seed `20261110` selects one proposal from
each of five classes × four recorded arms and shuffles presentation order.
`proxy_sample_key.json` separately retains identities, source-file hashes and the
saved literal-match grounding verdict. Do not consult the key before labeling.
CONTEXT_BLEED samples describe the pre-regeneration round-2 evidence.

Regeneration, without any model call:

```powershell
python -m services.critic.proxy_sample
```

## Deferred part B

Run from the merged, clean `main` checkout with its environment activated:

```powershell
python -m services.critic.round3_part_b --env-file C:/Umich/Projects/Nexus/.env
```

This script has not been run against benchmark data or providers. It performs no
Git mutation and requires HEAD's trace/label Git objects to match `bench-v1.1`.
It selects 12 DEV failures per class (60 total), with the frozen selection seed
and source-model stratification, uses stored Phase 2 DEV predictions, and runs
`original`, `v1_structured`, and `new` on the same selected views with DeepSeek.
All three use a common baseline registry snapshot, never a label-selected injected
prompt. Consequently this evaluates replacement applicability against a baseline
snapshot, not repair of the injected runtime configuration.

Arms run round-robin under a separate persistent aggregate **$1.00** ledger.
Every paid call reserves a conservative bound first; failed/unknown usage retains
its reservation. Exclusive protocol creation prevents a concurrent or accidental
second run. A cap stop preserves completed records and partial denominators.

Outputs stay under `reports/phase3/round3/`: protocol with commits/hashes/config,
per-call accounting, per-arm proposals, evidence, scoring-only truth and C3,
and summary JSON with C1, C2, fallback, literal grounding, exact/near specificity
(all sources and LLM only), and C3. Specificity is provided per class; overall
specificity is explicitly pooled across classes. MiniLM settings reuse round 2's
pinned revision, chunk pooling and cosine threshold. Detector misses generate no
proposal, remain in C3/pipeline coverage, and are separately counted; C1 over
generated proposals and conditional C2 have explicit denominators. No repair is
claimed by a successful dry run.

## Validation

- Unit suite: **243 passed**, including **47 new round-3 fixture cases**.
- Two existing sealed-dataset integrity tests excluded because they read TEST data.
- Ruff: repository-wide `ruff check .` clean.
- No real LLM generation, provider probe, detector inference or Part B run.

The unit command was `python -m pytest tests/unit
--ignore=tests/unit/nexusbench/test_dataset_integrity.py -q` with offline model/cache
settings and temporary output confined to the owned reports directory. Existing
classifier tests use local embedding/NLI classifiers; generative transports use
explicit mocks or HTTP fixtures. Infrastructure integration tests were not run.
