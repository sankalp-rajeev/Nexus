# TRAIL pre-registration amendment A3

Registered before TRAIL-B scoring, after development on the original 15 TRAIL dev traces, TRAIL-A and NexusBench DEV. Development numbers are not held-out results. Original pre-registration `8bc721b`, A1 `8222003`, A2 `999b28a` and disclosure `d19cb86` remain in force except where A3 explicitly supersedes them. This step performs no scoring and loads no TRAIL-B traces or labels.

## Frozen configuration

The frozen configuration is **detectors-v2 at commit `5660480`** (full hash `5660480673c8a4b3b1f2dbbd0dad6b2438ea3284`): **C1, C2, C4; C5 = final answer only**. No further detector, adapter, config, threshold, retrieval-rule, claim-splitting or scope changes are permitted before scoring.

- C1 retains A1-matched retrieval failures as TOOL_CALL with their errors; only successful source operations become retrieval spans. Recorded errors and the frozen explicit error-output markers qualify.
- C2 flags at least three same-tool calls within any window of six consecutive tool operations, regardless of success, using all-pairs normalized argument-token Jaccard >=0.8. Normalization and tool-operation projection are fixed by the frozen implementation.
- C4 normalizes entities and source text by casefolding, removing accents, normalizing punctuation/whitespace and canonicalizing thousands-separated numbers, searching all retrieved text. NLI model, thresholds and claim splitting are unchanged.
- C5 final answer only was chosen by the sole permitted selection on pooled TRAIL dev + A: F1 **0.387** (0.387097), versus **0.364** (0.363636) for every post-retrieval LLM output. No other parameter was selected or tuned.

Exact definitions are in `services/detectors_v2/DESIGN.md` and `config.json` at the frozen commit. The NLI model remains `cross-encoder/nli-deberta-v3-base`, revision `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`, with threshold 0.5034. Use the pinned local cache offline, without provider calls or model downloads. Frozen v1 files and thresholds remain unchanged.

## Scoring and metrics

Use **independent per-class flags, trace-level, exactly as in the TRAIL-A run**: `pipeline.fired(scores, unchanged_thresholds)` for each version, rather than its single priority-winning label. One trace may be positive for multiple classes. Use the same scorer and unchanged label/category/location handling for v1 and v2; only the frozen detector/adapter implementations differ.

Report TP/FP/FN/TN, precision and recall with **Wilson 95% intervals**, cohort and evaluated denominators, and GAIA/SWE Bench breakdowns. Undefined denominators remain undefined. HALLUCINATION uses final-answer scope and the existing source, readable-text and checkable-claim eligibility rules. Report each version's eligibility denominators and reasons explicitly. **Abstentions are counted separately and never treated as negatives or positives.** Preserve the original exclusion rules and report all exclusions by reason; no new exclusions based on observed results. Optional localization remains secondary under the original protocol and is omitted without an existing unambiguous locator.

## Primary and secondary mappings

**The ORIGINAL mapping is primary:**

- LOOP_DETECTED: Resource Abuse + Timeout Issues; prediction is the version's LOOP_DETECTED flag alone.
- TOOL_MISFIRE: API errors + Formatting Errors on original TOOL-origin spans, including A1/C1 conversions; prediction is the version's TOOL_MISFIRE flag.
- HALLUCINATION: Language-only + Tool-related hallucination under the unchanged category normalization; prediction is the version's HALLUCINATION flag on eligible traces.
- PLAN_DRIFT and CONTEXT_BLEED are not scored on TRAIL.

**C3 is a secondary analysis:** Resource Abuse/Timeout is detected if **v2-LOOP OR v2-TOOL_MISFIRE** fires. All gold labels, other classes and metrics remain unchanged; v1 retains its original mapping. C3 and the original mapping had identical counts on development data because every v2 MISFIRE-positive trace already fired v2 LOOP. Report both mappings regardless of which looks better on B; C3 cannot be promoted to primary after scoring.

## Claims hierarchy fixed before scoring

- **Primary hypothesis: LOOP.** Development expectation: precision approximately **0.8**, recall approximately **0.4**, under the original primary mapping. These are development expectations, not promised B results.
- **TOOL_MISFIRE:** if TRAIL-B has fewer than **5 gold-positive traces**, report descriptively only and make **no claim**. Development had three positives. Reaching five positives does not automatically authorize a claim.
- **HALLUCINATION:** report it, but expect performance near the applicable-cohort base rate: development precision **24%**, recall **100%**, with saturated predictions. Make **no improvement claim**.

## Version comparisons and guardrail disclosure

Report the existing frozen **v1 TRAIL-A result alongside** the B results, preserving it unchanged. Also score **v1 on TRAIL-B with the same scorer** for a **same-data v1-vs-v2 comparison**. The historical A result is context, not a paired substitute for the B comparison. Each version runs once on B under this protocol.

NexusBench DEV's independent-flag macro recall was unchanged at **0.953** (0.953333). Five-class priority-label macro recall fell **0.953 -> 0.930** (0.953333 -> 0.929804), a **0.0235 drop**, exceeding the **0.02 limit**, because v2-LOOP masks **4 MISFIRE decisions**. False alerts remained 8.474576 per 1,000 NORMAL. This guardrail breach is disclosed before scoring: **v2 is not a live-default candidate and v1 stays live**. No reselection or tuning follows this finding.

## Cohort, custody and mechanical join disclosure

TRAIL-B contains **63 traces: 49 GAIA and 14 SWE Bench**, fixed by A2 seed 20261114. Its ID-list SHA-256 is `7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f`. Dataset revision remains `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1`. The six pre-registered unjoinable GAIA exclusions remain outside A and B; no replacement or resampling is permitted.

Earlier disclosure, retained explicitly: before A2 was written, the pre-flight join check loaded and JSON-decoded the trace and label columns for all 148 rows, including the rows later assigned to TRAIL-B, to confirm the six pre-registered exclusions by trace ID. No label categories, evidence or descriptions were inspected, no detector was run, and no metric was computed on any trace during that check. A2 was split by seed, stratified only by gaia/swe_bench. TRAIL-B therefore remains unseen for detector development and evaluation. No later B trace/label inspection or detector execution has occurred, including in this amendment step.

All gated trace content, prompts, outputs, annotation evidence/descriptions and raw records remain under excluded `data/external/trail/` and must never enter commits, reports or demos. Only code, protocol, aggregate numbers and authorized trace IDs may be committed. NexusBench TEST stays sealed. Before future B scoring, verify committed protocols/manifests, the frozen configuration and v1 files, and the pinned local model. This amendment commit does not authorize scoring in the present step.

**TRAIL-B (63 traces) is scored once; no reruns, threshold, mapping or exclusion changes after loading it.**
