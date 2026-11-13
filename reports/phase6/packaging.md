# Step 6.4a: release prep for `nexus-llmops` 0.1.0rc1

Date: 2026-11-12. Nothing was published, no tag was created or pushed, and no publish workflow was
triggered. Everything here is local or in the repository; the first real publish is 6.4b.

## 1. Naming decision (D80)

| | |
|---|---|
| Distribution (what you `pip install`) | `nexus-llmops` |
| Import name | `nexus_llmops` |
| Compatibility alias | `nexus_agent` (same module objects) |
| Version | `0.1.0rc1` (PEP 440 pre-release, so `pip install --pre nexus-llmops`) |

Why `nexus-llmops`: the earlier name `nexus-selfheal` (D9) over-promised. The SDK traces; healing is
a separate service. `nexus-agent` is taken on PyPI by someone else (D9). `nexus-llmops` returned
404 on both pypi.org and test.pypi.org on 2026-11-12, so it is free on both (a name can still be
taken by someone else before the first upload).

Why the import name changed too, with an alias instead of keeping `nexus_agent`: a distribution
called `nexus-llmops` whose import is `nexus_agent` is confusing, and the public API (README,
examples, docs) now teaches `import nexus_llmops as nexus`. But 28 frozen files import
`nexus_agent` (counted at tag `phase4-test-scored` under the frozen paths: `services/detectors/`,
`services/critic/`, `bench/heal/`, `bench/agent.py`, `bench/detector_view.py`, and so on), and
frozen files must stay byte-identical. So the old name must keep working, without a second copy of
the code and without touching them.

## 2. The alias design

`sdk/nexus_llmops/` holds all the code (moved with `git mv`, history kept). `sdk/nexus_agent/` is
a single file, `__init__.py`, that does this when imported:

1. imports `nexus_llmops`;
2. walks that package with `pkgutil.walk_packages` (no hard-coded list) and registers every
   submodule and subpackage in `sys.modules` as `nexus_agent.<name>`, pointing at the same module
   object;
3. replaces itself in `sys.modules["nexus_agent"]` with the real `nexus_llmops` module.

Result: `nexus_agent is nexus_llmops`, `nexus_agent.models is nexus_llmops.models`, and so on for
every submodule. There are no `import *` copies, so global state such as the client set by `init()`
is shared, and class identity holds (`nexus_agent.models.Span is nexus_llmops.models.Span`).
Importing `nexus_agent.models` before either package gives the same objects, because Python imports
the parent `nexus_agent` first, which fills `sys.modules`. There is no DeprecationWarning in 0.1.x
(frozen research code imports the old name); new code should
use `nexus_llmops`.

Tests (`tests/unit/sdk/test_alias.py`, 16 tests, all passing; the SDK suite is 102 tests): for every submodule found by
`pkgutil` `nexus_agent.X is nexus_llmops.X`; `Span`, `SpanBatch`, `SpanType`, `NexusClient`,
`init`, `trace`, `span` are identical; `init()` through one name and `shutdown()` through the other
act on the same client (both directions); `import nexus_agent.models` first (also
`from nexus_agent.exporters.http import ...`) in a fresh interpreter gives the same objects;
importing the real name first still aliases the old one; a fresh interpreter run with `-W error`
imports it without any warning; and a module and a subpackage added *later* to a copy of the SDK are
picked up by the alias with no change to it.

Why the frozen code still imports `nexus_agent`: the frozen paths are protected by
`scripts/phase6/check_frozen.py` (empty diff against tag `phase4-test-scored`), which backs the
published Phase 2 and Phase 4 numbers. Rewriting 28 imports would change them for no behavioural
gain. The check passes, the DEV equivalence is still 359/359 through the alias, and the Phase 4,
heal, critic and detector unit tests pass (331 passed, 3 skipped for the sealed TEST split) with
the frozen files unchanged. Internal services keep their `nexus_agent` imports too (not mass
rewritten); the public surface, the SDK's own tests, and the smoke script use `nexus_llmops`.

`pip install -e /app/sdk` in the service Dockerfiles keeps working (hatch editable installs add the
`sdk/` directory to the path, so both packages are found). Only the collector image was rebuilt and
run for 6.4a; the others still carry the previous SDK copy, which is wire-compatible.

## 3. The OTLP mapping moved out of the SDK

`sdk/nexus_agent/integrations/otel.py` is now `services/collector/otel.py` (`git mv`, history
kept). It is server-side code (it parses an `ExportTraceServiceRequest` the collector already
decoded), nothing client-side used it, and it does not belong in a wheel that users install next to
their agent. Before moving, I confirmed no frozen file references `nexus_agent.integrations`
(`git grep` at the frozen tag: 0 hits; in the working tree the only importers were the collector
route, two tests and the parity script, all updated). The `integrations/` package is deleted.
`check_dist.py` also rejects any `integrations` path in the wheel.

## 4. `sdk/pyproject.toml`

```diff
-name = "nexus-selfheal"
-version = "0.1.0"
-description = "Zero-config observability and autonomous self-healing SDK for multi-agent AI pipelines"
+name = "nexus-llmops"
+version = "0.1.0rc1"
+description = "Python SDK for Nexus: fail-open agent tracing for the Nexus failure-detection and fix-verification service"
 license = { text = "MIT" }
+license-files = ["LICENSE"]
-keywords = [..., "self-healing"]
+keywords = ["llmops", "agents", "observability", "tracing", "mlops", "ai", "langchain", "crewai"]
-[tool.hatch.build.targets.wheel]
-packages = ["nexus_agent"]
+[tool.hatch.build.targets.wheel]
+packages = ["nexus_llmops", "nexus_agent"]
+[tool.hatch.build.targets.sdist]
+include = ["nexus_llmops", "nexus_agent", "README.md", "LICENSE", "pyproject.toml"]
```

Unchanged: authors, `requires-python = ">=3.11"`, dependencies (`httpx>=0.27`, `pydantic>=2.7`
only), classifiers, URLs. `sdk/LICENSE` is a copy of the repo's MIT license (the wheel ships it as
`dist-info/licenses/LICENSE`). `nexus_llmops.__version__` is `0.1.0rc1` too, and `check_dist.py`
fails the release if the two differ. `sdk/README.md` was rewritten for PyPI: install, the import
name and alias, a minimal example, fail-open and hardening behaviour (bounded queues, one retry,
counters, shutdown deadline, what is not guaranteed), the trace completion signal, and links to
the main repository. It no longer says "not yet published".

## 5. Local build

`python -m build sdk` (hatchling 1.33.0) then `twine check --strict sdk/dist/*`:

```
Checking sdk/dist\nexus_llmops-0.1.0rc1-py3-none-any.whl: PASSED
Checking sdk/dist\nexus_llmops-0.1.0rc1.tar.gz: PASSED
```

SHA-256: wheel `464beb1389cc9ba882f8f79bd6a325d68852562c9da9487c6d5ae68b719fb67f`,
sdist `b4e04da942e6f2ccb8ee01718962d1aa3508fd6abea5015d04c3143273720d12`.

Wheel contents (13 files, 21 KB): only `nexus_llmops/**`, the `nexus_agent/` alias, and metadata.
No `integrations/otel`, tests, data, `.env` or services code.

```
   1544  nexus_agent/__init__.py
   3363  nexus_llmops/__init__.py
  23273  nexus_llmops/client.py
   3323  nexus_llmops/config.py
   7454  nexus_llmops/decorators.py
   9265  nexus_llmops/models.py
     85  nexus_llmops/exporters/__init__.py
   2106  nexus_llmops/exporters/http.py
    921  nexus_llmops/exporters/stdout.py
   6024  nexus_llmops-0.1.0rc1.dist-info/METADATA
     87  nexus_llmops-0.1.0rc1.dist-info/WHEEL
   1092  nexus_llmops-0.1.0rc1.dist-info/licenses/LICENSE
   1081  nexus_llmops-0.1.0rc1.dist-info/RECORD
```

Sdist contents (`nexus_llmops-0.1.0rc1.tar.gz`): the same package files plus `README.md`, `LICENSE`,
`pyproject.toml`, `PKG-INFO` and a `.gitignore` that hatchling always adds. No tests, data or
services.

`METADATA` requires exactly `httpx>=0.27` and `pydantic>=2.7`.

## 6. Local clean-venv smoke test (`scripts/phase6/smoke_install.ps1`)

`powershell -File scripts\phase6\smoke_install.ps1 -Source local` (or `-Source testpypi -Version
0.1.0rc1` for 6.4b). It creates a fresh venv, installs the wheel with `--no-index` (the two
third-party dependencies are downloaded into a wheelhouse first; `nexus-llmops` itself is not fetched
from any index), runs from a directory outside the repo, starts the **lite collector** (in-process
queue, SQLite, no Kafka, no LLM), runs a small traced program with the SDK from the venv, stops the
collector and runs it again, then uninstalls. Result of the run on the final wheel: **SMOKE PASSED,
22 checks**:

| Phase | Checks |
|---|---|
| Install | imported from the venv's site-packages; version `0.1.0rc1`; `nexus_agent is nexus_llmops`; no `integrations` module and no `services` package in the install; no OpenTelemetry, protobuf, torch, transformers, FastAPI or Kafka packages pulled in |
| Collector up | program finished; `produced 5 / exported 5 / dropped_total 0`; 5 spans in the collector's SQLite; the trace was classified (a `LOOP_DETECTED` alert from three identical tool calls) |
| Collector down | collector confirmed down; program finished normally, same result value, 0.57 s in-process (0.9 s wall); `produced 5 / exported 0 / export_failed 5 / dropped_total 5`, so the counters show exactly the drops; a throttled warning was logged |
| Uninstall | `pip uninstall` ok; `import nexus_llmops` and `import nexus_agent` both fail afterwards |

The report is written to `data/phase6/runs/scratch/smoke_local.json` (ignored by git). The temp
venv is left under `data/phase6/runs/scratch/smoke/` and never deleted by the script.

## 7. `.github/workflows/publish.yml`

| | |
|---|---|
| Trigger | push of tags `v*` only |
| Default permissions | `contents: read` |
| `build` | venv with `build` and `twine`; `python -m build sdk`; `twine check --strict`; `scripts/phase6/check_dist.py --tag $GITHUB_REF_NAME`; upload artifact `dist` |
| `check_dist.py` fails if | tag version differs from `pyproject.toml` (PEP 440 normalised); `nexus_llmops.__version__` differs from it; not exactly one wheel and one sdist; the wheel holds anything but `nexus_llmops/**`, `nexus_agent/**` and `nexus_llmops-*.dist-info/**` (or any `integrations` path); the wheel lacks either `__init__.py`, METADATA or the license; the dependencies are not exactly `httpx` and `pydantic`; the sdist holds tests, data, services or env files |
| `publish-testpypi` | `needs: build`; `if: contains(github.ref_name, 'rc')`; `environment: testpypi`; `repository-url: https://test.pypi.org/legacy/` |
| `publish-pypi` | `needs: build`; `if: !contains(github.ref_name, 'rc')`; `environment: pypi` |
| OIDC | `id-token: write` (plus `contents: read`) on the two publish jobs only; none on `build` |
| Secrets | none: no token, password or `secrets.*`. Publishing uses PyPI Trusted Publishing |

Pinned to full commit SHAs (each with a version comment in the file):

| Action | Version | SHA |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/download-artifact` | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `pypa/gh-action-pypi-publish` | v1.14.3 | `7245906fb61fa33a13554f9d5fb856fe61758086` |

(The SHAs were resolved with `gh api` from each action's latest release tag on 2026-11-12. The build
job uses the runner's own `python3`, so no `setup-python` action is pinned or used.)

Tested without publishing: `tests/unit/phase6/test_release_packaging.py` parses the workflow
(trigger, permissions, environments, conditions, repository URL, every `uses:` pinned to a 40-hex
SHA with a version comment, no secrets) and exercises `check_dist.py` on good and bad
distributions. The workflow itself has not run: it only runs on a `v*` tag, which this step does
not create. The first real run is 6.4b.

## 8. Release procedure

One-time setup, done by the repository owner (not by this step, and not in the workflow):

1. TestPyPI and PyPI: add a *pending trusted publisher* for the project `nexus-llmops`: owner
   `sankalp-rajeev`, repository `Nexus`, workflow `publish.yml`, environment `testpypi` (TestPyPI)
   and `pypi` (PyPI).
2. GitHub repository Settings, Environments: create `testpypi` (no approval needed) and `pypi` with
   **required reviewers**, so a PyPI publish waits for a manual approval.

Release candidate to TestPyPI (6.4b):

1. On `phase-6-demo`, with `sdk/pyproject.toml` and `nexus_llmops/__init__.py` both `0.1.0rc1`:
   `git tag v0.1.0rc1` then `git push origin v0.1.0rc1`.
2. `publish.yml` runs: build and gates, then `publish-testpypi` (the tag contains `rc`).
3. Verify with `scripts\phase6\smoke_install.ps1 -Source testpypi -Version 0.1.0rc1`.

Final release to PyPI, after the Phase 6 PR (#5) merges to `main`:

1. On `main`, change the version to `0.1.0` in both `sdk/pyproject.toml` and
   `sdk/nexus_llmops/__init__.py` (the gate fails if they differ or if the tag differs), commit, and
   let CI pass.
2. `git tag v0.1.0` on that `main` commit, then `git push origin v0.1.0`. (The workflow checks the
   version, not the branch: tag from `main` only.)
3. `publish.yml` runs the build and gates, then `publish-pypi` stops at the `pypi` environment until
   a reviewer approves it. Approve, then verify with a fresh `pip install nexus-llmops`.

A tag cannot be re-used: PyPI refuses to upload the same version twice, and tags are never moved or
deleted here. If an RC is wrong, bump to `0.1.0rc2`.

## 9. Release record: `0.1.0rc1` on TestPyPI (step 6.4b)

| | |
|---|---|
| Tag | `v0.1.0rc1`, lightweight, on commit `793cf3ccf2b71d1b2234d542bedb6a3c1e70237c` (`phase-6-demo`); only this tag was pushed |
| Workflow run | https://github.com/sankalp-rajeev/Nexus/actions/runs/43375663694 (Publish, 2026-11-13) |
| Jobs | `build` success (28 s), `publish-testpypi` success (21 s), `publish-pypi` skipped (tag contains `rc`) |
| TestPyPI | https://test.pypi.org/project/nexus-llmops/0.1.0rc1/ |
| Uploaded | `nexus_llmops-0.1.0rc1-py3-none-any.whl` (21,354 bytes) and `nexus_llmops-0.1.0rc1.tar.gz` (17,599 bytes) |

SHA-256 of the files (TestPyPI JSON API `digests.sha256` equals the CI artifact `dist`, byte for byte):

| File | SHA-256 |
|---|---|
| wheel | `b357219790d04aac5550589c5b449eb9e1c99bcd1c03c7e111471695d4a2fece` |
| sdist | `a03e585690f06a1305b6e60c785c0f9dd6fa01bf468841f8b42f9b4cf1d6c9b0` |

The index metadata: `requires_python >=3.11`, `requires_dist httpx>=0.27, pydantic>=2.7`, the
description is the Markdown `sdk/README.md` (`text/markdown`, which `twine check --strict` validated).
The wheel also carries a PyPI attestation (`publish/v1`, subject digest = the wheel hash above);
its publisher is GitHub, repository `sankalp-rajeev/Nexus`, workflow `publish.yml`, environment
`testpypi`.

Why the 6.4a local hashes differ from these: the same commit built on Windows has CRLF line endings
in the working tree (`core.autocrlf=true`), and CI builds from an LF checkout. After normalising CRLF
to LF every file inside the two wheels is identical (only `RECORD` differs, as it holds the hashes).
The CI artifact is the release; local builds are for checking only. Nothing was altered to make them
match.

Caveat on the page check: the HTML pages on test.pypi.org answered with a CAPTCHA ("Client
Challenge") to curl and to the built-in browser, and the challenge was not solved. The page content
was verified through the JSON API and the attestation (`/integrity/.../provenance`) instead; the
rendered README itself was not looked at in a browser.

### Safe install (TestPyPI)

TestPyPI is a separate index with different, unvetted projects, so a resolve that mixes it with PyPI
(`--extra-index-url`) can pick up a look-alike dependency. Never do that. Install in two steps:

```
pip install "httpx>=0.27" "pydantic>=2.7"
pip install --no-deps --index-url https://test.pypi.org/simple/ nexus-llmops==0.1.0rc1
```

`scripts/phase6/smoke_install.ps1 -Source testpypi` does exactly this, retrying the second step for up
to 12 x 20 s while the index catches up (it served the release on the first attempt here). The
run: **SMOKE PASSED, the same 22 checks as the local run** (`data/phase6/runs/scratch/smoke_testpypi.json`,
ignored by git): install from TestPyPI, version `0.1.0rc1`, both import names identical, no server
code or heavy dependencies; collector up: `produced 5 / exported 5 / dropped_total 0`, 5 spans in the
lite DB, `LOOP_DETECTED` alert; collector down: the program finished normally (0.56 s in-process,
0.9 s wall) with `produced 5 / exported 0 / export_failed 5 / dropped_total 5`; uninstall removes
both imports.

### Reproducing Phase 5 scripts

Phase 5 scripts reproduce at commit `75771ab` (they reference pre-rename SDK paths such as
`sdk/nexus_agent/client.py`; the frozen `scripts/phase5/` files cannot be edited, so they are not
valid on `phase-6-demo` after the rename).

### GitHub environment check (read only, via the API; nothing was changed)

| Environment | Exists | Required reviewers | Deployment rule |
|---|---|---|---|
| `testpypi` | yes | none (intended) | none |
| `pypi` | yes | **none** | custom policy `v*` of type **branch** (not tag); admins can bypass |

Two gaps to fix in Settings, Environments, `pypi` before the `v0.1.0` tag (not done here):
1. No required reviewer is set, so `publish-pypi` would not wait for a manual approval.
2. The `v*` rule is a *branch* rule. A tag run is evaluated against tag rules, so as it stands the
   `v0.1.0` tag would probably be refused by the environment (or, if the policy is later widened,
   would not be restricted to tags). Replace it with a rule of type **Tag** matching `v*`.