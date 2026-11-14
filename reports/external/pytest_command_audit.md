# external-validation pytest command audit

Audit source: the current conversation's execution records, matched to the nexus-external working directory. No sealed artifact contents were opened for this audit. Commands below are copied exactly, including the Python executable, selectors, options and temporary paths. Environment assignments and subsequent non-pytest commands in the same shell block are omitted.

**Earlier invocations audited: 28 (26 plain pytest; 2 DEV-only runner). No plain-pytest invocation selected tests/unit/heal/test_a3.py or tests/unit/test_reporting_hygiene.py, including their parent directories.** The full DEV-only invocation selected both modules with the registered skips and finished with 891 passed, 9 skipped.

No new D82-style TEST-reading exposure entry is warranted by these selections. The approved D82 in merged PR #8 records separate post-release/media-refresh runs; it is retained unchanged when main is integrated. All further local tests use scripts/phase5/pytest_dev_only.py -p no:deepeval.

## Run 1: 2026-11-13T19:12:04.971Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py
```

## Run 2: 2026-11-13T19:12:35.148Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-temp
```

## Run 3: 2026-11-13T19:17:14.648Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-temp-corrected
```

## Run 4: 2026-11-13T19:18:11.085Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_setup.py --basetemp=data/external/trail/pytest-setup
```

## Run 5: 2026-11-13T19:19:23.533Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/external/test_trail_setup.py --basetemp=data/external/trail/pytest-final
```

## Run 6: 2026-11-13T19:27:13.410Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/external/test_trail_setup.py --basetemp=data/external/trail/pytest-a1
```

## Run 7: 2026-11-13T19:28:55.793Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_a1.py --basetemp=data/external/trail/pytest-a1-applicability
```

## Run 8: 2026-11-13T20:03:08.943Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_a2.py --basetemp=data/external/trail/pytest-a2
```

## Run 9: 2026-11-13T20:12:13.329Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail.py tests/unit/external/test_trail_a2.py tests/unit/external/test_trail_a1.py tests/unit/external/test_trail_setup.py tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-score-before
```

## Run 10: 2026-11-13T20:13:58.494Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail.py --basetemp=data/external/trail/pytest-score-final
```

## Run 11: 2026-11-13T20:19:16.984Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail.py --basetemp=data/external/trail/pytest-score-crashfix
```

## Run 12: 2026-11-13T20:23:24.663Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail.py tests/unit/external/test_trail_a2.py tests/unit/external/test_trail_a1.py tests/unit/external/test_trail_setup.py tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-score-afterfix
```

## Run 13: 2026-11-13T21:03:54.111Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail.py tests/unit/external/test_trail_a2.py tests/unit/external/test_trail_a1.py tests/unit/external/test_trail_setup.py tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-results-final
```

## Run 14: 2026-11-13T21:20:48.087Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_diagnosis.py --basetemp=data/external/trail/pytest-diagnosis
```

## Run 15: 2026-11-13T21:28:40.344Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_diagnosis.py --basetemp=data/external/trail/pytest-diagnosis-report
```

## Run 16: 2026-11-13T22:06:48.009Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_diagnosis.py --basetemp=data/external/trail/pytest-diagnosis-final
```

## Run 17: 2026-11-13T22:08:02.486Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_trail_diagnosis.py tests/unit/external/test_score_trail.py tests/unit/external/test_trail_a2.py tests/unit/external/test_trail_a1.py tests/unit/external/test_trail_setup.py tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py --basetemp=data/external/trail/pytest-part3-final
```

## Run 18: 2026-11-13T22:16:29.513Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/sdk tests/unit/phase6/test_readme_numbers.py tests/unit/phase6/test_release_packaging.py tests/unit/test_results_md_pins.py tests/unit/detectors/test_detectors.py --basetemp=data/external/trail/pytest-merge-v2
```

## Run 19: 2026-11-13T22:25:47.308Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_detectors_v2.py --basetemp=data/external/trail/pytest-v2-first
```

## Run 20: 2026-11-13T22:32:15.390Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_detectors_v2.py tests/unit/external/test_v2_evaluation.py --basetemp=data/external/trail/pytest-v2-evaluation
```

## Run 21: 2026-11-13T22:34:06.484Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/sdk tests/unit/phase6/test_readme_numbers.py tests/unit/phase6/test_release_packaging.py tests/unit/test_results_md_pins.py tests/unit/detectors/test_detectors.py --basetemp=data/external/trail/pytest-v2-candidate
```

## Run 22: 2026-11-13T22:55:46.242Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_detectors_v2.py tests/unit/external/test_v2_evaluation.py --basetemp=data/external/trail/v2_scope_tests
```

## Run 23: 2026-11-13T22:57:40.397Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/sdk tests/unit/phase6/test_readme_numbers.py tests/unit/phase6/test_release_packaging.py tests/unit/test_results_md_pins.py tests/unit/detectors/test_detectors.py --basetemp=data/external/trail/v2_final_checks
```

## Run 24: 2026-11-13T23:14:38.488Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external/test_score_trail_b.py tests/unit/external/test_score_trail.py tests/unit/external/test_detectors_v2.py tests/unit/external/test_v2_evaluation.py --basetemp=data/external/trail/b_scorer_synthetic_checks
```

## Run 25: 2026-11-13T23:17:32.144Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/sdk tests/unit/phase6/test_readme_numbers.py tests/unit/phase6/test_release_packaging.py tests/unit/test_results_md_pins.py tests/unit/detectors/test_detectors.py --basetemp=data/external/trail/b_final_checks
```

## Run 26: 2026-11-14T01:00:58.964Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: plain pytest. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' -m pytest -q tests/unit/external tests/unit/collector/test_openinference.py tests/unit/collector/test_otlp.py tests/unit/collector/test_otlp_semconv.py tests/unit/sdk tests/unit/phase6/test_readme_numbers.py tests/unit/phase6/test_release_packaging.py tests/unit/test_results_md_pins.py tests/unit/detectors/test_detectors.py tests/unit/healer/test_auto_apply.py --basetemp=data/external/trail/final_pr_merge_tests
```

## Run 27: 2026-11-14T01:21:09.394Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: DEV-only. Sensitive audit targets selected: none.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' scripts/phase5/pytest_dev_only.py tests/unit/phase6/test_trail_publication.py tests/unit/phase6/test_readme_numbers.py tests/unit/collector/test_replay_export.py tests/unit/test_results_md_pins.py -q --basetemp=data/external/trail/trail_publication_tests
```

## Run 28: 2026-11-14T01:24:38.218Z

Working directory: `C:\Umich\Projects\nexus-external`. Runner: DEV-only. Sensitive audit targets selected: tests/unit/heal/test_a3.py, tests/unit/test_reporting_hygiene.py.

```powershell
& 'C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe' scripts/phase5/pytest_dev_only.py tests/unit tests/e2e -q --basetemp=data/external/trail/final_pr_full_tests
```

The command audit does not run or repeat a detector evaluation, change a result, or infer artifact access from result contents.
