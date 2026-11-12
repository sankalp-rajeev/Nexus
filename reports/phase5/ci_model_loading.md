# CI model-loading regression: diagnosis and fix

## Evidence before changes

The last main push CI run before PR #4 was
[43143079344](https://github.com/sankalp-rajeev/Nexus/actions/runs/43143079344),
commit `81289ed95be6a16327929ff8dca34001f1079e6b`, conclusion success.
The decoded logs explicitly show both cases passed:

```text
test job 130934472298:
tests/unit/classifier/test_embedder.py::test_nli_contradiction_high PASSED
integration job 130935552176:
tests/integration/test_crewai_examples.py::test_crewai_examples_classified_correctly PASSED
```

The failing PR run was
[43302738402](https://github.com/sankalp-rajeev/Nexus/actions/runs/43302738402),
head `b3bbefc742a70f6f0a46e0fe94b1a9141b704392`. Its test job
131477911403 failed; integration was skipped because it depends on that job.
Relevant captured failure log:

```text
WARNING nexus.classifier.embedder:embedder.py:66
nexus-classifier: NLI model failed to load (We couldn't connect to
'https://huggingface.co' to load the files, and couldn't find them in
the cached files. ...); contradiction_score will be 0.0 for all traces
nli = <services.classifier.embedder._NullNLIScorer object ...>
AssertionError: expected high contradiction, got 0.000
AssertionError: trace_crew_hall: expected FailureType.HALLUCINATION, got FailureType.NORMAL
```

Phase 5 changed the CI execution path to the full DEV-guarded test runner.
The relevant additions versus main were:

```diff
--- .github/workflows/ci.yml
+ pip install -r scripts/phase5/requirements.txt
+ python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
+ python scripts/phase5/pytest_dev_only.py -p no:deepeval -v ...
--- scripts/phase5/pytest_dev_only.py
+ os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ...)
--- docker-compose.phase5-load.yml (classifier service only)
+ HF_HUB_OFFLINE: "1"
+ TRANSFORMERS_OFFLINE: "1"
+ .../models--cross-encoder--nli-MiniLM2-L6-H768:...:ro
```

The root cause was incomplete model staging: the preload populated only the
embedding model, not NLI. The original offline flags correctly prevented an
unstaged model from downloading during tests; the existing classifier fallback
then returned zero scores. The local cache contained NLI and masked the missing
CI dependency. Offline flags and test socket guards protect approved egress and
frozen-detector reproducibility. Model acquisition must finish before the guarded
test process starts; model staging is the fix.

The same offline assignments also existed in Phase 5's standalone run.py,
followup.py and sdk_overhead.py launchers. All four launchers are restored exactly
to b3bbefc, retaining their original offline policy. The full scripts/phase5/
diff against b3bbefc is empty. Root conftest had no Phase 5 change before this
fix; its new change is the dependency guard.

Before this fix, Phase 5 made no changes to root tests/conftest.py or
requirements-dev.txt, and set no HF_HOME/HF_HUB_CACHE/TRANSFORMERS_CACHE cache
directory environment variables. The only extra requirement was portalocker.
The Docker read-only mount and offline settings affect only the classifier
container; CI's Python host tests do not use that container.

## Configuration-only fix

The failing tests use **cross-encoder/nli-MiniLM2-L6-H768**, as configured by
services/classifier/embedder.py. The separate frozen Phase 4 detector uses
**cross-encoder/nli-deberta-v3-base**. CI now downloads and caches both, plus
the embedding model, at exact revisions in .github/model-revisions.json:

- cross-encoder/nli-deberta-v3-base: `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`
- cross-encoder/nli-MiniLM2-L6-H768: `b95119ce93d3e065de6214e38cd4a97b0f2f2c6d`
- sentence-transformers/all-MiniLM-L6-v2: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`

These are the same revisions as the locally passing caches. Each actions/cache
key includes OS, model name and full revision; there is no fallback restore key.
Both CI jobs use the shared preparation action. Pinned inference artifacts are
staged as local model-name directories, so the unchanged constructors resolve
exact local snapshots with the original offline flags and guards intact.
Weights are ignored by Git. No model/scorer substitution
or detector code edit is used.

All original Phase 5 HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE assignments are kept,
including the host launchers and Docker classifier service. The preparation
action, revision manifest, workflow, preparation helper and ignored model cache
from e6aa0ab are otherwise unchanged. The NLI-dependent fixtures retain the
required_classifier_nli check
which fails with **NLI model not loaded** before any score/classification assertion
if the real scorer is unavailable. No test is skipped to conceal the dependency.

## Local HF cache provenance

For each configured model, the local HF cache's snapshot folder name and
refs/main were read and compared with the exact configured pin. Only model IDs
and these hashes were inspected/reported; no other cache or environment values
were printed. All three values match for every model.

| Model ID | Snapshot folder name | refs/main | Configured pin |
|---|---|---|---|
| cross-encoder/nli-deberta-v3-base | 6c749ce3425cd33b46d187e45b92bbf96ee12ec7 | 6c749ce3425cd33b46d187e45b92bbf96ee12ec7 | 6c749ce3425cd33b46d187e45b92bbf96ee12ec7 |
| cross-encoder/nli-MiniLM2-L6-H768 | b95119ce93d3e065de6214e38cd4a97b0f2f2c6d | b95119ce93d3e065de6214e38cd4a97b0f2f2c6d | b95119ce93d3e065de6214e38cd4a97b0f2f2c6d |
| sentence-transformers/all-MiniLM-L6-v2 | 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 | 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 | 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 |

## Validation

The full local suite at e6aa0ab passed: **451 passed, 9 skipped, 0 failures/errors**,
including both reported cases and all 12 integration tests. The restored-offline
follow-up also passed **451 passed, 9 skipped, 0 failures/errors**, in 33.47
seconds, through scripts/phase5/pytest_dev_only.py with -p no:deepeval. Raw
results remain in ignored local state.
The same eight sealed-TEST skips and one auxiliary skip remain. The missing-
model guard was separately exercised with the existing null scorer: it raises
the exact "NLI model not loaded" diagnostic instead of accepting zero scores.
Raw test logs/XML remain under ignored data/phase5/runs/.

check_frozen.py passed before/after; detector/scoring sources and model IDs
remain unchanged. Ruff and workflow/composite YAML validation pass. Fixed CI
execution is visible in PR #4's Actions checks; the final handoff links the
completed run. No paid provider runs or sealed data access are involved.
