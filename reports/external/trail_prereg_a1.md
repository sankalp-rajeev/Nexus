# TRAIL pre-registration amendment A1

Registered on 2026-11-13 on `external-validation`, before any external-test scoring code or run exists. This is a prospective amendment to [trail_prereg.md](trail_prereg.md), committed at `8bc721b2d404449f1b2de6b1e8461777852cafaa`. It fixes an adapter observability gap identified on the sealed dev slice. It uses no label comparisons, precision/recall, detector-based tool selection, or external-test inspection.

Dataset revision remains `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1`; seed remains `20261113`. The 15 dev traces (12 GAIA + 3 SWE Bench), 133 sealed test traces (105 + 28), ID lists, and SHA-256 manifest remain unchanged. The manifest SHA-256 remains `4081a888f8d624b257cc8a6fe1648a0709160b05154bfd5df59967bf6c16f061`. All gated trace/annotation content remains private under the excluded `data/external/trail/`; none is copied into code, reports, tests, or the demo. Tool names below are the specifically authorized schema identifiers only.

## Fixed retrieval rule

The list was selected from **dev schema only: `tool.name` and `openinference.span.kind`**, before rerunning NLI. No hallucination labels or other label columns were read for A1. The reasons are conservative interpretations of the tool interfaces' names, not conclusions from their outputs or annotations.

Map an existing span to Nexus `retrieval` exactly when:

1. `openinference.span.kind`, normalized to uppercase as in the existing adapter, is `RETRIEVER`; or
2. that kind is `TOOL` and `tool.name` exactly, case-sensitively equals one of the following six names.

| Exact tool name | Schema-based reason |
| --- | --- |
| `web_search` | Returns search results/snippets from external web sources. |
| `visit_page` | Reads the text of a visited external page. |
| `page_down` | Reads a subsequent viewport of the currently visited source page. |
| `page_up` | Reads an earlier viewport of the currently visited source page. |
| `find_on_page_ctrl_f` | Locates a passage/view in an already retrieved source page. |
| `inspect_file_as_text` | Reads file/document contents as text that can ground an answer. |

The fixed set is `{"web_search", "visit_page", "page_down", "page_up", "find_on_page_ctrl_f", "inspect_file_as_text"}`. No substring matching, tool renaming, content classification, or later expansion is permitted. OpenInference `RETRIEVER` kind remains sufficient without a tool name.

SWE Bench dev exposes only `final_answer` as a TOOL name, so **no repository file-view tool is added speculatively**. If a source reader appears only in the sealed test schema, it does not expand this list. `final_answer` is an answer emission, not retrieved evidence; `visualizer` does not establish a text-reader interface; `find_archived_url` is an archive locator rather than a page/document-text reader. Those names remain unretagged.

`services/collector/openinference.py` applies this rule before the existing OTLP mapper. Matching TOOL spans retain captured `input.value` arguments, unchanged names, raw parameter-schema metadata, IDs, parents, times, status, errors, and output. Their captured `output.value` becomes the retrieval span's output without synthesizing source text. Failed or output-missing retrievals are not promoted to usable evidence by the frozen detector. No duplicate spans are created; all other mapping behavior is unchanged.

The unchanged frozen LOOP/MISFIRE `tool_calls` helper excludes Nexus retrieval spans. Thus retagged spans follow the frozen retrieval behavior and no longer enter that helper; A1 introduces no compensating detector change or duplicated tool view. Their original OpenInference TOOL identity remains in metadata: the original restriction of API/Formatting gold annotations to **tool-origin** spans still applies, including a TOOL-origin span retagged as retrieval. Taxonomy categories and location resolution rules are otherwise unchanged.

## Applicability and scoring scope

HALLUCINATION may be scored **only on traces that reach the frozen NLI path**, meaning successful nonempty retrieved context and at least one checkable final-answer claim. The original readable-source gate also remains: at least one frozen premise has 20 stripped characters and three alphabetic words of at least two characters each. Source and claim checks are independent of gold labels. The frozen source extractor, claim extractor, model revision, threshold, and flag calculation remain unchanged.

**Abstentions must be counted and reported with reasons and never treated as negative predictions.** In particular, no usable retrieval text -> `no_successful_retrieval_text`; usable retrieval text but no checkable claim -> `no_checkable_claims`. A below-readability source is reported separately as an eligibility exclusion, even if the frozen NLI function returns a value. Report the full sealed-test denominator, join-label exclusions, applicability exclusions/abstentions, and evaluated denominator per class. A zero evaluated denominator remains not assessable, with undefined precision/recall.

**PLAN_DRIFT is not scored**, including exploratory scoring: explicit declared plans were present in **0/15 dev traces**. **CONTEXT_BLEED is not scored**: no cross-session memory is exposed. The unmodified pipeline may execute their functions during the required dev smoke check, but A1 reports no decisions, detector values, or accuracy for either class.

The A1 dev-only checker reads the trace column through the existing sealed-ID loader and never reads labels. It executes the frozen pipeline on all 15 converted dev traces, with the exact pinned local NLI model `cross-encoder/nli-deberta-v3-base` at `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`. Model artifacts are copied from the existing revision-specific cache to the ignored workspace model directory; Hugging Face and Transformers offline modes are enabled. No provider calls, remote inference, substitutes, threshold tuning, or external scoring are performed. Numeric outputs and predictions are discarded.

Applicability counts: **7/15 reach the real frozen NLI path; 8/15 abstain**, all eight because they have no successful, nonempty mapped retrieval text (`no_successful_retrieval_text`). GAIA: **7/12 reach NLI, 5/12 abstain**. SWE Bench: **0/3 reach NLI, 3/3 abstain**. All seven NLI-path traces also pass the original readability gate; there are zero additional readability exclusions and zero claim-only abstentions. Only aggregate path/abstention counts and reasons are recorded in [trail_dev_applicability_a1.json](trail_dev_applicability_a1.json). This replaces the original adapter's historical 0/15 NLI-path result; it is not an accuracy estimate.

## Predeclared label-join exclusions

The following six GAIA **test** traces are excluded for all scored classes, as already established by the original ID-only manifest. This list is copied from that committed manifest, without reopening test labels. No row-position join, ID inference, JSON repair, or replacement/resampling is permitted.

| Trace ID | Reason |
| --- | --- |
| `0035f455b3ff2295167a844f04d85d34` | Label object lacks `trace_id`; no joinable label. |
| `5b5a35053775cbf29701c171e6675853` | Label object lacks `trace_id`; no joinable label. |
| `5e5dc94e090341c564d582f551a0cddb` | Label object lacks `trace_id`; no joinable label. |
| `5ec1cd43eb8ae4094e93a4892ff0f06f` | Label object lacks `trace_id`; no joinable label. |
| `6cc6dc35a28bbed6cfd873756094bc16` | Label object lacks `trace_id`; no joinable label. |
| `a96c6811716c0473b86a23321db79c34` | Invalid label JSON; no joinable label. |

This leaves 127 potentially label-eligible test traces before HALLUCINATION applicability and other original class-specific exclusions. Dev traces remain excluded from all test metrics.

## Unchanged commitments and verification

Everything else in the original pre-registration is unchanged: data custody/version, sealed partitions, label categories, trace-level per-class analysis, optional span localization, Wilson 95% intervals, undefined-denominator handling, exclusion transparency, per-class frozen flags, and a single future sealed-test run. A1 supersedes only retrieval mapping and the explicit applicability/scoring-scope statements above. The original protocol and part 1 coverage artifact remain unchanged as historical records.

**frozen detectors, thresholds unchanged, scored once, reported as is**

Frozen `services/detectors/` and its thresholds still match `phase2-detectors-frozen`; all 75 shared frozen-file comparisons pass after CRLF normalization. NexusBench TEST is untouched. The final focused synthetic/OTLP suites passed **127 tests** (121 adapter/compatibility/setup tests and six A1 applicability tests). Unit tests use synthetic spans and synthetic NLI stubs only; the separate dev execution check uses the real pinned local model. Secret and dev-content-copy scans precede the explicit-path commit and branch push. No external-test scorer is included.
