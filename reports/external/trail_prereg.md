# TRAIL external validation pre-registration

Registered on 2026-11-13, on `external-validation`, before external test scoring or a part 2 evaluator exists. Part 1 performs acquisition, an ID-only join audit, dev-only adapter work, and a dev-only execution smoke check. It computes no precision, recall, confusion matrix, or external test predictions.

## Data version, custody, and sealed partition

Dataset: `PatronusAI/TRAIL`, Hugging Face revision **b424ce63d5973d5dcd7169b1bc3c07ccdee276d1**. Authenticated access was granted and both parquet files were downloaded at that revision. The local Hub download revision markers are checked before use. `HF_TOKEN` is read from the workspace `.env` and is never printed or committed. No LLM/provider calls are used.

TRAIL is gated. Its trace content, prompts, outputs, annotation evidence/descriptions, raw exports, and caches remain under `data/external/trail/`, excluded by `.git/info/exclude`. They must never be committed, redistributed outside a gated/private repository, quoted in reports, or used in the demo. Tracked artifacts contain code, this protocol, aggregate coverage, and the explicitly authorized trace-ID lists only.

Source split counts are **gaia: 117** and **swe_bench: 31**, totaling 148. Seed **20261113** selects 12 GAIA and 3 SWE Bench traces for dev. The remaining **133** are sealed external test traces: 105 GAIA and 28 SWE Bench. Dev never enters reported test metrics.

Selection uses Python `random.Random(20261113)`, iterates source split names in sorted order, samples from each sorted trace-ID list with quotas 12 and 3, and writes each selected/complement list in sorted order. Selection does not use labels, categories, error frequency, or detector behavior. Detailed dev span inspection began only after split commit **d198c60**. The selection is never resampled.

The ID-only manifest is [trail_split/manifest.json](trail_split/manifest.json). Its exact LF-byte SHA-256 is `4081a888f8d624b257cc8a6fe1648a0709160b05154bfd5df59967bf6c16f061`. Each digest below hashes ASCII trace IDs only, one sorted ID per LF-terminated line. Git attributes preserve LF for these artifacts.

| ID list | Traces | SHA-256 |
| --- | ---: | --- |
| `dev_gaia.txt` | 12 | `b103285993d5a5ef5093d3d7b83e43cea8b54c9baea5651541f82bba4aebe718` |
| `dev_swe_bench.txt` | 3 | `da62c1dd5faf3c15149c1150d1e8b8bfc48d0e15cc8a5169d03bdf541840ee6f` |
| `test_gaia.txt` | 105 | `cda3d31e67d7b2eb5b3b9c16e42bf9feba2f8b6b0854cf94047fd78141a5637d` |
| `test_swe_bench.txt` | 28 | `8f4c5195ecc54e64f6a88683de285c945469cec98dfcf63a7dc619089f9ca519` |

`trace` and `labels` are JSON-string columns. Join by decoded `trace_id`, never by row position. The ID-only audit found 111 joinable GAIA labels and 31 joinable SWE Bench labels, no duplicate trace/label IDs, no cross-split ID overlap, and no valid label IDs without traces. Six GAIA traces lack a joinable label: five label objects omit `trace_id`; one label string is invalid JSON. Their IDs and reasons are in the manifest. All six lie in the sealed test partition; all 15 dev traces have joinable labels. These six are predeclared all-class exclusions, leaving **127 potentially label-eligible test traces** before class-specific exclusions. Do not repair malformed annotations or infer missing IDs from adjacent rows. No test label categories, descriptions, evidence, or span content were inspected in part 1.

## Adapter contract

`services/collector/openinference.py` converts nested or flat OpenInference JSON to an OTLP request, then reuses `services.collector.otel.span_batches`. It assembles `CompleteTrace` in completion-time order and passes the result through the existing `bench.detector_view` before frozen detector execution. It makes no network calls and takes no label argument.

| Captured attribute/field | Nexus mapping |
| --- | --- |
| `openinference.span.kind` | LLM -> `llm_call`; TOOL -> `tool_call`; AGENT/CHAIN -> `agent_step`; RETRIEVER -> `retrieval`; EMBEDDING -> `llm_call`; unrecognized/absent -> `custom` |
| `input.value`, `output.value` | Input/output text, with structured values serialized through the existing OTLP mapper |
| `llm.input_messages`, `llm.output_messages`, indexed `.N.message.*` | GenAI message aliases; numeric index ordering; text messages flattened by the existing mapper; mixed tool-call/multimodal data retained as structured JSON |
| `tool.name`, `tool.parameters` | `metadata.tool_name`, parameter schema retained in `metadata["otel.attributes"]["tool.parameters"]`; actual call arguments come from `input.value`, never from the parameter schema; missing actual arguments are flagged |
| `llm.model_name`, prompt/completion token counts | Model and numeric token metadata; the detector view removes the model convenience alias as usual |
| Trace/span/parent IDs, `child_spans` | Validated identity, nesting and parent linkage; conflicting parents, cycles, duplicate IDs and foreign-trace spans rejected |
| Timestamp, ISO-8601 duration | Start/end and duration, with completion ordering; exported event timestamps lacking a zone inherit their enclosing span's explicit zone |
| Status and exception events | `error_type` / `error_message` through the existing OTLP error mapping |
| `nexus.agent.role`, `nexus.agent.plan_steps` | Explicit `planner` role and declared tool-name list, if captured; no plan inferred from prompts, task descriptions, or free-form reasoning |

Root input and final output use the outermost captured agent boundary with content. Input falls back to captured span input if no agent input exists; output falls back to the outermost/latest LLM output if no agent output exists. Tool outputs are not concatenated into a synthetic answer. Tool names are not renamed to satisfy the detector retrieval allowlist. Unknown original attributes remain private in OTLP metadata. Synthetic unit fixtures contain no TRAIL material.

Dev-only coverage comprises **15 traces / 662 spans**: 25 AGENT, 190 CHAIN, 289 LLM, 104 TOOL, and 54 unspecified. `input.value` occurs on 598 spans, `output.value` on 511; indexed message attributes occur on 289 input and 289 output spans; tool name and parameters occur on all 104 TOOL spans. Captured root input and final output are available on all 15 traces. The aggregate artifact is [trail_dev_coverage.json](trail_dev_coverage.json).

## Label mapping and unit of analysis

The primary unit is **one trace per class**, with multiple positive classes permitted. A positive gold class is the OR of its qualifying annotations in `errors[].category`. Ignore `scores` and never derive labels from annotation descriptions, evidence, impact text, or detector outputs. Match the named taxonomy categories case-insensitively with normalized whitespace/punctuation; spelling variants or unrecognized categories must be documented without expanding the mapping after seeing results.

| Nexus class | TRAIL annotations | Scope |
| --- | --- | --- |
| LOOP (`LOOP_DETECTED`) | Resource Abuse + Timeout Issues | Primary; broad TRAIL resource/timeout failures may exceed the frozen repeated-successful-tool-call definition |
| TOOL_MISFIRE | API errors + Formatting Errors **on tool spans** | Primary; annotation `location` must identify an existing converted TOOL span |
| HALLUCINATION | Language-only hallucination + Tool-related hallucination | Primary only when source text is present under the eligibility rule below |
| PLAN_DRIFT | Goal Deviation | Exploratory only, and only with an explicit declared tool plan |
| CONTEXT_BLEED | None | Not tested; no metrics or validation claim |

For tool-span qualification, resolve hexadecimal span IDs in `location` against the converted trace. An unresolved or ambiguous location on an API/Formatting annotation makes that trace's TOOL_MISFIRE gold status unassessable unless another qualifying annotation already establishes a positive. A resolved non-tool location does not qualify. Other class labels are unaffected. Dev inspection confirmed that location fields can reference existing span IDs; no annotation content is copied here.

Predictions in part 2 will be the **per-class flags from the frozen `pipeline.fired(scores, unchanged_thresholds)`**, computed from one `compute_scores` invocation per eligible sealed trace. Do not use the single winning class from precedence to suppress another class. `CONTEXT_BLEED` may execute as part of the unchanged pipeline but is not evaluated. No calibrated probabilities, new judge, extra labeler, or threshold tuning will be introduced.

Optional span localization is secondary: only where a gold location resolves uniquely, count a predicted location within **+/-1 span** of any qualifying gold span in the deterministic converted completion order. Report its own denominator and ambiguity exclusions, separately from trace metrics. Omit localization if the class lacks a pre-existing unambiguous locator; do not invent one from annotation descriptions or tune it on test.

## Signal eligibility and dev-only execution check

Availability is determined without gold categories. A readable source text has at least **20 stripped characters** and **three alphabetic words of at least two characters each**. HALLUCINATION is eligible only if at least one premise returned by the **unchanged `hallucination.retrieved_context`** satisfies that predicate. That function uses successful RETRIEVAL spans or successful tool calls whose unchanged names belong to the frozen retrieval allowlist (`search_docs`, `search`, `retrieve`, `retriever`, `knowledge_search`). Generic tool stdout is counted separately and is not sufficient. An eligible trace with no checkable claims is excluded with `no_checkable_claims`, never silently treated as a correct negative. No source -> exclude HALLUCINATION with `no_frozen_source_text`, regardless of its gold label.

PLAN_DRIFT additionally requires a nonempty explicit `planner` tool-name list from the adapter. A general task, list of available tools, or free-form suggested steps is not that declaration. Missing plan -> `no_declared_tool_plan` for exploratory drift evaluation.

| Needed signal / smoke result | GAIA dev (12) | SWE Bench dev (3) | Total (15) |
| --- | ---: | ---: | ---: |
| At least three captured tool steps, with captured input | 7 | 0 | 7 |
| Tool error captured | 7 | 0 | 7 |
| Error followed by same tool within two tool calls (arguments need not match for this availability check) | 6 | 0 | 6 |
| Successful tool output passes readable-text gate | 7 | 0 | 7 |
| Source text reaches frozen NLI retrieval path | 0 | 0 | 0 |
| Explicit declared tool plan | 0 | 0 | 0 |
| Frozen pipeline returns a well-formed output | 12 | 3 | 15 |

These are input-availability aggregates, not positive detector counts. The smoke check discards detector scores and class predictions. HALLUCINATION abstained on all 15 because no retrieved context reached its frozen path; its NLI inference branch was therefore **not exercised on TRAIL dev**. Drift's function executes but its plan-dependent branch cannot be assessed on dev. This is an observability limitation, not evidence of accuracy. LOOP and TOOL_MISFIRE retain their existing three-successful-identical-call and error-plus-identical-arguments retry rules. Do not exclude traces merely because no repeated call, error, or retry occurred: these absences can be valid negatives.

Frozen files match `phase2-detectors-frozen` (`d293ab6dd06047467691b1d2750bed6e703b438c`) and the shared phase 4 freeze, including independent CRLF-normalized working-byte checks. Thresholds remain HALLUCINATION **0.5034**, CONTEXT_BLEED **1.0**, PLAN_DRIFT variant **ungrounded_any_source**. The LF-normalized threshold file SHA-256 is `b5bcaf76b03c1e0b2b6be963da6bdc2ac1321bf589485616dca6c76566978a08`. The existing NLI revision pin is `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`; any future eligible NLI inference must use that exact local model, without provider calls or substitutes. NexusBench TEST and all frozen artifacts remain untouched.

## Predeclared metrics, exclusions, and reporting

For each primary class, report eligible trace count, positive gold count, TP/FP/FN/TN, **precision = TP/(TP+FP)** and **recall = TP/(TP+FN)**, each with a **Wilson 95% interval**. No pooled primary metric or selection of favorable classes. Report exploratory PLAN_DRIFT separately. Retain the original GAIA/SWE Bench breakdown and report aggregate results; do not rebalance the sealed test set.

For a binomial numerator x and denominator n, use z = 1.959963984540054, p = x/n, d = 1 + z^2/n, center = (p + z^2/(2n))/d, half-width = z*sqrt(p*(1-p)/n + z^2/(4*n^2))/d, interval = [center-half-width, center+half-width]. A zero denominator yields **undefined**, with its denominator reported; never replace it by zero, an epsilon, or a favorable interval. Zero eligible traces means the class is **not assessable**.

Report counts of excluded traces per class and reason, using a mutually exclusive first-applicable order: invalid label JSON; missing label `trace_id` / no joined label; conversion failure; malformed category/location that prevents gold assessment; no frozen source text (HALLUCINATION); no checkable claims (HALLUCINATION); no declared tool plan (PLAN_DRIFT). Also disclose marginal availability counts so overlapping instrumentation limitations are visible. Orphan label records are audited separately and are never trace-level negatives. Dev's 15 design exclusions are shown separately from exclusions among the 133 sealed test traces. Known test exclusions are one invalid-label-JSON trace and five missing-label-ID traces, all GAIA. Other test exclusions remain unmeasured until the single registered run.

If conversion or required pinned local NLI loading fails, stop before producing a partial accuracy report and document the failure. Conversion failures, if any, must be counted transparently; do not silently drop or repair traces and rerun. Missing captured arguments/tool identity should be disclosed as instrumentation limits, without retrospectively excluding predicted errors. No changes to adapters, taxonomy mapping, eligibility, thresholds, or denominators after test inspection; any later change requires a separately labeled amended study, not replacement of this registered result.

**frozen detectors, thresholds unchanged, scored once, reported as is**

Part 1 ends after committing this protocol, the adapter, synthetic tests, and aggregate coverage. Part 2 requires a subsequent instruction. No scoring implementation is included in this commit.

## Part 1 verification

All commands use Windows PowerShell and `C:\Umich\Projects\nexus-phase6\.venv\Scripts\python.exe`. The adapter, OTLP compatibility, split/join, and dev-isolation suites passed **105 tests**. Tests use synthetic exports only. Test temporary files are under the excluded private directory. The dev checker verifies all split digests and 75 normalized frozen-file comparisons before execution. Reproduction entry points are `scripts/external/prepare_trail.py` (`--download` only when acquisition is needed) and `scripts/external/trail_dev_check.py`; neither implements external test scoring. Run the four focused suites in `tests/unit/collector/test_openinference.py`, `tests/unit/collector/test_otlp.py`, `tests/unit/collector/test_otlp_semconv.py`, and `tests/unit/external/test_trail_setup.py`, with a fresh `--basetemp` beneath `data/external/trail/` and Hugging Face/Transformers offline modes enabled.
