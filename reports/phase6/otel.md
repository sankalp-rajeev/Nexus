# Phase 6 step 6.3: OpenTelemetry GenAI ingestion

Field-by-field contract: [`docs/otel_mapping.md`](../../docs/otel_mapping.md).
Raw parity result: `results/phase6/otel_parity.json`. No LLM or provider call was made
anywhere in this step; every model in the tests and the example is a fake function.

## Pinned versions

| What | Pin |
|---|---|
| `semantic-conventions-genai` | commit `e6658f14c9d9ea0760825f029cb82e7673f48fab` |
| Core `semantic-conventions` (last release that carried `gen_ai.*`) | `v1.41.1`, commit `ead83b9b0fa36540c1642fce46e874f002ac23f1` (`v1.42.0` moved the GenAI group out) |
| `opentelemetry-proto` (collector, server side) | `1.42.1` |
| `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` (tests, example) | `1.42.1` |

The commits are constants in `sdk/nexus_agent/integrations/otel.py` and a unit test asserts
they appear in the mapping doc.

## Accepted names (current names win)

| Legacy form | Current form |
|---|---|
| `gen_ai.system` | `gen_ai.provider.name` (old values `vertex_ai`, `gemini`, `az.ai.inference`, `az.ai.openai` renamed too) |
| `gen_ai.usage.prompt_tokens` | `gen_ai.usage.input_tokens` |
| `gen_ai.usage.completion_tokens` | `gen_ai.usage.output_tokens` |
| per-message log events before 1.37 (`gen_ai.system/user/assistant/tool.message`, `gen_ai.choice`) | `gen_ai.input.messages` / `gen_ai.output.messages` attributes |
| `gen_ai.prompt` / `gen_ai.completion`, `gen_ai.prompt.N.*` / `gen_ai.completion.N.*` | same |
| `gen_ai.client.inference.operation.details` event | attributes on the span |
| `gen_ai.input.messages` / `gen_ai.output.messages` / `gen_ai.system_instructions` as span attributes | current form, read first |

Every alias that was used is recorded in `metadata["otel.legacy_aliases"]`; the raw
attributes always stay in `metadata["otel.attributes"]`. A span with no content is accepted
and stored, flagged `nexus.content_missing=true` (not applied to non-GenAI spans). Tests: 45 in
`tests/unit/collector/test_otlp_semconv.py`, one or more per alias, plus the content-missing
cases and an HTTP acceptance test for a content-less export.

## Parity (DEV split only)

Method: `scripts/phase6/otel_fixtures.py` converts DEV traces to OTLP with current semconv
names, loading them through the DEV whitelist before deserialising. Both paths classify with
the same service classifier. Trace IDs are derived from the DEV id plus a salt and every
trace is marked `nexus.synthetic=true`.

- **Native path:** SDK spans, `TraceBuffer`, `ClassifierService.process_trace`.
- **OTLP path:** wire bytes, `span_batches`, JSON round trip, `TraceBuffer`, same service.

### (a) In-process, all 359 DEV traces (4,692 spans)

| Mapping | `failure_type` match | Mismatches |
|---|---|---|
| Final (text-only messages projected to plain text) | **359 / 359 (100 %)** | 0 |
| Before the fix (every message list kept as a JSON envelope) | 214 / 359 (59.6 %) | 145 |

Final run, additional checks: triggered rule matches on 359/359, failure span index on
359/359, span order preserved 359/359; anomaly score absolute difference median 0.006, max
0.016 over the 288 traces with a score. Per DEV label every label is at 100 %.

**All 145 mismatches of the first mapping were the same case**: native `HALLUCINATION`,
OTLP `NORMAL`, rule `embedding+svm` on both sides (so the stage-2 text path, never a rule).
Patching any single field group (`duration_ms`, `input`, `output`, `error_message`,
`tool_name`, `model/tokens`) from the native trace into the OTLP trace restored
`HALLUCINATION` in none of them; patching `input` **and** `output` together reproduced the
native outcome in all 145 (`explain()` in `scripts/phase6/otel_parity.py`, stored per trace
in the baseline result). The cause was a real mapping bug in my first design: the native
spans carry plain text, and wrapping it in a JSON message envelope changed the per-span
feature string that MiniLM embeds (type, model, `input[:200]`, `output[:200]`, ...), which
moved the trace across the SVM boundary. Fix: text-only message lists are projected to plain
text (one message: no wrapper; several: `role: text` lines; system instructions first as a
`system` message); anything with a non-text part keeps its structure as JSON. The classifier
was not touched.

Differences that remain by design and did not change a single classification:

| Field | Why |
|---|---|
| `duration_ms` (all spans) | OTLP has integer nanoseconds, native is a float with float32 noise; the text feature uses it |
| `sdk_version` (all spans) | the collector stamps its own |
| `metadata.tool_name` on 130 memory-operation spans | semconv has no counterpart for a memory tool name |

### (b) End to end through the running stack, 20-trace DEV subset

Label-stratified, sha256-ordered (deterministic). Each trace sent twice with a fresh nonce:
once as native spans to `POST /v1/spans`, once as gzip protobuf to `POST /v1/traces`. Both
go through Kafka, assembler, Postgres and the classifier container.

| | Result |
|---|---|
| Classified on both paths | 20 / 20 |
| `failure_type` match | **20 / 20 (100 %)**, 0 mismatches |
| Assembled span count equal to the sent count | all 20 on both paths |
| Alerts published for these synthetic traces | 0 |

By outcome: 3 CONTEXT_BLEED, 3 HALLUCINATION, 3 NORMAL, 3 OTHER_FAILURE, 3 PLAN_DRIFT traces
all got `HALLUCINATION` on both paths (what this classifier predicts for them);
3 LOOP traces `LOOP_DETECTED` (`loop_detector`); 2 TOOL_MISFIRE traces `TOOL_MISFIRE`
(`tool_error_retry`).

Caveats, stated plainly:

- This measures **parity between two ingestion paths**, not classifier accuracy. The native
  path itself maps most non-rule DEV labels to `HALLUCINATION`; parity reproduces that.
- The first end-to-end attempt used a 150 s wait, and the classifier needs about 15 s per
  trace on this machine, so only 4 of 20 pairs had arrived; the harness reported 4/20 and
  I raised the wait to 1,200 s and reran from scratch (new nonce). The 20/20 above is that
  second run. The first run's classifications for its own nonce are in the topic but unused.
- OTLP traces are seen 0 to 20 s after their native twins in that run (loop traces 0 s; OTLP completes
  after the 30 s inactivity timeout, native on `metadata.final`; the classifier queue
  dominates the rest). Expected, and in the mapping doc.

## Official-exporter interop test

`tests/integration/test_otlp_exporter_interop.py`: the real `opentelemetry-sdk` with
`BatchSpanProcessor` and `OTLPSpanExporter` (gzip and uncompressed) exports over loopback
HTTP to the running collector; then Kafka, assembler and classifier on the `nexus-phase6`
stack. 5 passed in 37 s: export SUCCESS, collector span-count delta, Postgres assembly with
plain-text content, `tokens_used == 30`, `provider == fake`, `nexus.synthetic is True`, the
looping trace classified `LOOP_DETECTED` by `loop_detector` with `failure_span_id` a tool
span, the normal trace classified, zero alerts. The test skips itself unless the collector
reports Kafka, Postgres is reachable and the classifier and assembler groups have members.

## Example

`examples/otel_plain/run_demo.py` imports only `opentelemetry-sdk` and the OTLP exporter
(no `nexus` import). Runs against the stack, all with `--synthetic`:

| Run | Trace | Spans | Nexus result |
|---|---|---|---|
| `--scenario loop` | `01f6e8cdd7885c14c6e01a047662bad3` | 6 | `LOOP_DETECTED`, `loop_detector`, confidence 1.0, `failure_span_id` `4575eb2909ed96b0` |
| `--scenario normal` | `3d321651917a8c0b7820603ca3f2861b` | 4 | `NORMAL`, `embedding+svm`, anomaly 0.746, confidence 0.897 |
| `--scenario normal --no-content` | `6832dfb0a2c4a74b626d355905975360` | 4 | `NORMAL`, `embedding+svm`, anomaly 0.678, confidence 0.893 (spans flagged `nexus.content_missing`) |

A real auto-instrumentation env-var snippet is in the README, documentation only; it was not
run because it would call a model provider.

## `sdk/nexus_agent/integrations/otel.py`

What it does: it is the OTLP to Nexus projection. It takes `ResourceSpans` from the
collector's decoded request and yields `SpanBatch`es (the same `Span` model the SDK emits)
with the mapping, aliases and flags above. It is only imported by
`services/collector/routes/otlp.py`; no client-side code uses it. It imports no
OpenTelemetry package, and its single protobuf helper (`MessageToDict`) is imported lazily
inside the function that needs it. A subprocess unit test asserts that importing
`nexus_agent` and the module pulls in no `opentelemetry*` or `google.protobuf*` modules.

Recommendation for 6.4: an `[otel]` extra is **not** needed, because the SDK has no
OpenTelemetry dependency and nothing on the client side consumes the module. The real
question is placement: it is a server-side converter, so either move it into
`services/collector/` (cleanest) or exclude it from the published SDK wheel. An `[otel]`
extra would only make sense if Nexus later ships a client-side `SpanProcessor` that depends on
`opentelemetry-sdk`. I changed nothing about packaging.

## Known limits (documented, not fixed)

- Content is opt-in in OpenTelemetry. Without it Nexus gets structure only, and **three
  content-less identical-looking tool spans trip `loop_detector`** (an empty input hashes the
  same). This is covered by a documented-limit test, and the spans are flagged so a caller
  can tell. I did not change the rule.
- `EVENT_ONLY` capture sends log records; Nexus has no OTLP logs endpoint, so that content is
  never seen.
- A trace is complete 30 s after its last span, not on a final flag.
- Arbitrary custom attributes are kept in `otel.attributes`, not as first-class metadata.

## Process disclosure

While starting the parity work I ran `Get-Content data/nexusbench/labels.csv -TotalCount 3`
to see its columns; it printed two rows of the sealed TEST split. I did not use them for
anything: every number above comes from `dev_labels()` / `dev_traces()` only, and no TEST
trace was opened, loaded, converted or run. Reported here because the rule is absolute.
