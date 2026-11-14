# Phase 6 release: nexus-llmops 0.1.0

Date: 2026-11-13. Release approved by Sankalp (tag, GitHub release, one production deploy with alias); the
PyPI publish was approved by Sankalp in the GitHub `pypi` environment.

## Tag and commit

| | |
|---|---|
| Tag | `v0.1.0`, annotated, message "nexus-llmops 0.1.0" (tag object `f93b3ae4b47e65693d27276c62d5bca59bc09eb4`) |
| Commit | `b9a95e64c242ee02717c97a2e2c399eacab8ed85`, the merge of PR #5 into `main` |
| Pre-flight | `origin/main` = PR #5 merge; CI on it green (test, integration: [run 43507901963](https://github.com/sankalp-rajeev/Nexus/actions/runs/43507901963)); `git diff origin/main origin/phase-6-demo` empty; `sdk/pyproject.toml` and `nexus_llmops.__version__` are `0.1.0`; a fresh build of the merged tree passed `twine check --strict` and `check_dist.py --tag v0.1.0` |

## Publish workflow

[Publish run 43509058336](https://github.com/sankalp-rajeev/Nexus/actions/runs/43509058336):

- `build`: success (sdist + wheel, `twine check`, `check_dist.py` tag/version match and wheel contents).
- `publish-testpypi`: skipped (not an `rc` tag).
- `publish-pypi`, first attempt: failed before reaching review. The `pypi` environment's deployment rule
  allowed `v*` as a branch pattern only, so the tag ref `v0.1.0` was rejected ("Tag "v0.1.0" is not
  allowed to deploy to pypi due to environment protection rules"). Nothing was published. Sankalp added a
  `v*` tag rule to the environment; the tag was not moved.
- `publish-pypi`, re-run of the failed job only (same run, same build artifact): waited for review,
  approved by `sankalp-rajeev` in environment `pypi`, success (21:32:14 to 21:32:41 UTC).

## PyPI

https://pypi.org/project/nexus-llmops/0.1.0/ (JSON API `https://pypi.org/pypi/nexus-llmops/0.1.0/json`):
version `0.1.0`, not yanked, `Requires-Python >=3.11`, MIT, dependencies `httpx>=0.27`, `pydantic>=2.7`.

| File | Size (bytes) | SHA-256 on PyPI | CI artifact `dist` |
|---|---|---|---|
| `nexus_llmops-0.1.0-py3-none-any.whl` | 21,366 | `4039764311780b4af635526d2bd2e77fd6be17bb9019495a37ede13e074e5152` | match |
| `nexus_llmops-0.1.0.tar.gz` | 17,653 | `1d5c881c3c4760548f29ed62657df1cf784022bb30c4347d5c711cbc0cc5d00d` | match |

Attestations (PyPI integrity API, `/integrity/nexus-llmops/0.1.0/<file>/provenance`): each file has a
`https://docs.pypi.org/attestations/publish/v1` attestation whose subject digest is the file's SHA-256
above, from Trusted Publisher `{"kind": "GitHub", "repository": "sankalp-rajeev/Nexus", "workflow":
"publish.yml", "environment": "pypi"}`.

## Smoke test from real PyPI

`powershell -File scripts\phase6\smoke_install.ps1 -Source pypi -Version 0.1.0 -ExpectWheelSha256 4039…5152`
(new `pypi` mode: `pip --isolated install --index-url https://pypi.org/simple/ nexus-llmops==0.1.0`, no extra
index; collector is the Docker lite stack on `127.0.0.1:18000`). Result: **22/22 checks passed**, plus the
two README-quickstart checks.

- Install: pypi.org served the release on the first attempt; pip's install report shows the wheel came from
  `files.pythonhosted.org` with SHA-256 `4039…5152` (the CI artifact's); imported from the fresh venv;
  version `0.1.0`; `nexus_agent is nexus_llmops` (module objects identical); no server-side code; no heavy
  or server dependencies (installed: nexus-llmops, httpx, httpcore, h11, anyio, idna, certifi, pydantic,
  pydantic_core, annotated-types, typing_extensions, typing-inspection).
- README quickstart: `example.py` taken verbatim from README.md (agent name made unique per run) ran and its
  trace appeared completed, with 2 spans, in `GET /v1/lite/snapshot`.
- Collector up: the looping program exported 5/5 spans, 0 dropped; the trace (5 spans) was classified
  `LOOP_DETECTED`.
- Collector down (`docker compose -f docker-compose.lite.yml stop`): the program finished normally in 1.5 s
  wall time with an unchanged result; counters `produced 5`, `exported 0`, `export_failed 5`,
  `dropped_total 5`, `queued 0`.
- Uninstall: `pip uninstall` succeeded; `import nexus_llmops` and `import nexus_agent` both fail afterwards.

The lite container is left stopped; its volume `nexus-lite_nexus_lite_data` was not removed. The `local`
mode was re-run after the script change: 22/22.

## GitHub release

https://github.com/sankalp-rajeev/Nexus/releases/tag/v0.1.0: "nexus-llmops 0.1.0", latest, not a
pre-release. Notes are the CHANGELOG 0.1.0 entry with links to PyPI and the demo.

## Production deploy

- Built from the merged tree: `git archive` of `dashboard/` at `b9a95e6` plus the existing Vercel project
  link (so untracked local folders were not uploaded). `vercel deploy --prod` to project `nexus-demo`:
  deployment `dpl_ERgYWKocDJQyKTg7KahZto1QYogK`, `https://nexus-demo-eampeicfu-sankalp-rajeevs-projects.vercel.app`,
  target production, Ready.
- `vercel alias set <deployment> nexus-llmops.vercel.app`. Vercel Deployment Protection covers manual aliases,
  so the alias first served the Vercel login page; `vercel domains add nexus-llmops.vercel.app nexus-demo`
  made it a project domain (public, follows production, like the project's existing production domain).
- https://nexus-llmops.vercel.app returns 200 with the demo page; `/replay.json` is byte-identical to
  `dashboard/public/replay.json` at `b9a95e6`.

## Screenshot and console check

Headless Edge over CDP against https://nexus-llmops.vercel.app/ at 1440, 768 and 390 px; outputs (not
committed) in `data/phase6/runs/scratch/demo/prod/` (11 section shots and one full-page shot per width,
`check.json`).

| Width | Fonts loaded | Horizontal overflow | Elements wider than viewport |
|---|---|---|---|
| 1440 | yes | no | none |
| 768 | yes | no | none |
| 390 | yes | no | none |

Console errors or warnings: none. Failed or 4xx/5xx requests: none. Requests to any host other than
`nexus-llmops.vercel.app`: none.

## Redeploy after PR #7 (2026-11-13)

Approved by Sankalp: one Vercel production deploy of `dashboard/` from `main` after the PR #7 merge.

- Source: `main` at `8ad7e9ee2f39344ac84bfaf207f54db9147fb219` (merge of PR #7); CI on that commit green
  (test, integration: [run 43524402470](https://github.com/sankalp-rajeev/Nexus/actions/runs/43524402470)).
- Built from a `git archive` export of `dashboard/` at that commit plus the existing Vercel project link, so
  untracked local folders (`.hallmark/`, `.impeccable/`, `.diagram-work/`) were not uploaded.
- `vercel deploy --prod` to project `nexus-demo`: deployment `dpl_3gPAzWJRzaJwrCH5H9FSzqdTvnAF`,
  `https://nexus-demo-9wyf7y8nf-sankalp-rajeevs-projects.vercel.app`, target production, Ready. The project domain
  `nexus-llmops.vercel.app` follows production and points at it (no alias change needed).
- https://nexus-llmops.vercel.app returns 200. The deployed bundle carries the new lede ("Nexus detects failures
  live…"), the story diagram (horizontal SVG from 1024 px, vertical below; checked in the screenshots), the
  "What it costs to run" section and the "View full diagram" link; `/nexus-architecture-dark.png` is
  byte-identical to `main`.
- `/replay.json`: same JSON content as `main`, but **not byte-identical**: the served file ends in CRLF
  (396,896 bytes) where the committed blob ends in LF (396,895 bytes). Cause: `git archive` on this Windows
  checkout applies `core.autocrlf=true` to text files. A redeploy from an export made with
  `git -c core.autocrlf=false archive` would fix it; not done, as only one deploy was approved.
- Screenshot and console check (headless Edge, 1440/768/390, outputs in `data/phase6/runs/scratch/demo/prod3/`,
  not committed): fonts loaded, no horizontal overflow, no element wider than the viewport, no console errors or
  warnings, no failed or 4xx/5xx requests, no requests to any other host.

**Correction to the 0.1.0 deploy above.** Its `replay.json` check compared the served file with the Windows
working copy (CRLF), not with the committed blob, and that deploy used the same `git archive` export, so its
served `replay.json` most likely also ended in CRLF. "Byte-identical" there means identical to the working copy;
the JSON content matched.

## Final TRAIL publication deploy (2026-11-14 UTC)

Approved by Sankalp: **one** Vercel production deploy from `main` after PR #9. This entry records that
deployment; it does not authorize another deploy or a merge of the release-record PR.

- `git fetch origin` confirmed `origin/main` at `d7a163c4c4db2108fdffa2f6c7f3f767d8b7b172`, the merge of
  [PR #9](https://github.com/sankalp-rajeev/Nexus/pull/9). Before the deployment, both `test` and `integration`
  passed on that exact main commit: [CI run 43552326508](https://github.com/sankalp-rajeev/Nexus/actions/runs/43552326508).
- Exported only `dashboard/` at that commit using `git -c core.autocrlf=false archive --format=zip`.
  The archive contains 55 committed files, uses LF for text, and passed the secret scan. Local-only
  `.hallmark/`, `.impeccable/` and `.diagram-work/` directories, dependencies, build output and environment
  files were absent. The existing `nexus-demo` project link was added only to the private export.
- Ran `vercel deploy --prod --yes --scope sankalp-rajeevs-projects` once from the exported dashboard.
  Project `nexus-demo`, deployment `dpl_8x6pq3qKKzzSjY7YRa51LMJAq4ix`, target production, **Ready**:
  [deployment](https://nexus-demo-n6x11z2zw-sankalp-rajeevs-projects.vercel.app),
  [inspection](https://vercel.com/sankalp-rajeevs-projects/nexus-demo/8x6pq3qKKzzSjY7YRa51LMJAq4ix).
  The existing project domain followed production automatically; no domain or alias configuration changed.
- https://nexus-llmops.vercel.app returns **200**. The TRAIL evidence section is visible, including its
  claims hierarchy and the disclosure that v2 is not live and v1 stays live.
- Served `/replay.json` is **byte-identical to the committed blob**, read with
  `git show origin/main:dashboard/public/replay.json` at the source commit above, rather than to the
  Windows working copy: **405,704 bytes**, SHA-256
  `87838d8d6bf655e3249e6399b7bd698133e3b3fff6e0f7fc68a1c3538baf1088`.
  The LF export resolves the earlier CRLF discrepancy recorded above.
- The story SVG renders horizontally at 1440 px and vertically at 768 and 390 px. The "View full diagram"
  link loads `/nexus-architecture-dark.png` from the same production host with status 200 and PNG content;
  its response bytes also match the committed image at that source commit.

Headless Chromium screenshot and console/network checks passed at **1440, 768 and 390 px**. At each
width: fonts loaded; no horizontal overflow or elements wider than the viewport; no console errors or
warnings; no failed or 4xx/5xx requests; no off-host requests. Full-page, story-diagram and TRAIL-section
screenshots, `checks.json`, the LF archive and deployment metadata are private and git-excluded under
`data/phase6/runs/scratch/demo/prod-final/`.

No TRAIL trace content was added to the publication or this record. No detector was rerun, no provider
was called, and no frozen detector, threshold or live default changed. No Docker/WSL command was used.
