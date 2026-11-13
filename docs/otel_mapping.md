# OpenTelemetry GenAI to Nexus mapping

Implemented in `sdk/nexus_agent/integrations/otel.py` (the projection) and
`services/collector/routes/otlp.py` (the `/v1/traces` receiver). Measured parity
with the native SDK path is in [`reports/phase6/otel.md`](../reports/phase6/otel.md).

## Pinned conventions

The GenAI conventions are `Development` status and moved out of the core
repository, so two pins are recorded. Both are constants in `otel.py` and a test
fails if this page stops mentioning them.

| What | Pin |
| --- | --- |
| GenAI conventions repo | [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) |
| Pinned commit (it has no tagged release) | `e6658f14c9d9ea0760825f029cb82e7673f48fab` (`main`, 2026-11-06) |
| Equivalent core `semantic-conventions` release | `v1.41.1` (commit `ead83b9b0fa36540c1642fce46e874f002ac23f1`). `v1.42.0` is the release that deprecated `gen_ai.*` in core and moved it to the repo above, so `v1.41.x` is the last core version that carried them. |
| Wire format | OTLP/HTTP 1.x: `application/x-protobuf` or `application/json`, identity or gzip |
| Python packages used by the tests and examples | `opentelemetry-proto`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` `==1.42.1` |

A newer pinned commit changes only attributes this page lists as supported; the
mapping never drops an attribute (see "Provenance").

## Content capture: read this first

**Nexus's detectors are text-based.** The classifier embeds a trace from each
span's type, model, tokens and the first 200 characters of its `input` and
`output`; the hallucination signals compare an `llm_call`'s output against its
input with an NLI model and an embedding distance; loop and tool-misfire rules
hash each span's `input`. All of that reads prompt and response *text*.

GenAI instrumentations **do not capture that text by default.** The conventions
make `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `gen_ai.retrieval.query.text`,
`gen_ai.memory.query.text` and `gen_ai.memory.records` opt-in, because they usually
hold user data. With the default, Nexus receives structure, timing, models, token
counts and errors, and no text.

To turn content on for an instrumentation that follows the current conventions:

```bash
# 1. emit the current (gen_ai_latest_experimental) names instead of the 1.30-era ones
export OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental

# 2. capture content on SPANS (Nexus ingests traces only, so not EVENT_ONLY)
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=span_only
```

The second variable's name depends on the instrumentation version:
`opentelemetry-instrumentation-openai-v2` 2.4b0 and `opentelemetry-util-genai` 1.3b0
read `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (values `span_only`,
`event_only`, `span_and_event`, `no_content`; plain `true` on the pre-opt-in path).
The pinned convention text names it `OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT`
(values `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT`, `NO_CONTENT`; default
`NO_CONTENT`). Set the one your instrumentation documents. Choose `SPAN_ONLY` or
`SPAN_AND_EVENT`: `EVENT_ONLY` sends content as OTel *log records*, and Nexus has
no log endpoint, so that content never arrives. A custom hook that uploads content
to external storage and records only `*_ref` URIs also leaves Nexus without text.

**What degrades without content** (measured/observed behaviour, not a promise
about detector quality):

| Signal | Without content |
| --- | --- |
| Span ingestion, trees, durations, errors, model and token counts | Unaffected. |
| `input` / `output` | `""` / `None`, and the span is flagged `metadata["nexus.content_missing"] = true`. |
| Loop rule | Every call of the same tool with empty arguments looks identical, so repeated *different* calls look like a loop. The frozen loop rule can fire on a trace that is not looping. It needs `gen_ai.tool.call.arguments` to tell calls apart. **The live classifier guards this** (below). |
| Tool-misfire rule | Needs an errored tool call followed by an identical call; with empty inputs, any later tool call of that tool counts as identical. Not guarded. |
| HALLUCINATION detector | Needs retrieved context and a final answer; with no text it returns "nothing to check" and does not fire. |
| PLAN_DRIFT, CONTEXT_BLEED detectors | PLAN_DRIFT reads tool arguments and results as well as the plan; CONTEXT_BLEED reads memory results. Without content they do not fire. |
| Legacy classifier (embedding / PatchCore / SVM) | Only with `NEXUS_CLASSIFIER=legacy`. It runs on type, model, duration, error flag and token counts only, so treat its label as low-information. |

The flag is for consumers that need to tell "this span said nothing" from "this
span's content was not captured". **The live classifier (the scored detectors, 6.3b)
reads it in one place**: if every span in every loop run is flagged
`nexus.content_missing`, the loop verdict is dropped. The trace is classified without
it (usually `NORMAL`), the reason is `insufficient_content` in `triggered_rule`, no
alert is raised, and `/health` counts it as `insufficient_content_suppressed`. The
frozen detector is not edited; the guard sits in the adapter
(`services/classifier/live_detectors.py`). A loop in which any span has captured
arguments still alerts.

## Transport

POST `/v1/traces` on collector port 8000 (lite host port 18000).
Accepts `application/x-protobuf` (`ExportTraceServiceRequest`) and
`application/json` (OTLP JSON: hexadecimal IDs, nanosecond timestamps encoded
as decimal strings). Identity and gzip content encodings work. Compressed and
decompressed requests are limited to 4 MiB. JSON unknown protocol fields are
ignored, as required by OTLP; unknown *attributes* are retained.

The entire request is mapped and validated before publishing. The adapter
returns `SpanBatch` objects of at most 100 spans, so a larger OTLP export is
not truncated. A successful response is HTTP 200 with an empty
`ExportTraceServiceResponse` in the request's encoding. Partial queue failures
return HTTP 200 with `partialSuccess.rejectedSpans`; total queue failure returns
503 for retry. Invalid payloads return 400, oversized payloads 413, unsupported
media types or encodings 415. gRPC, metrics and logs are outside this adapter.

Point an exporter at the collector with
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://<collector>:8000/v1/traces` and
`OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`. (Setting only
`OTEL_EXPORTER_OTLP_ENDPOINT` appends `/v1/traces` for you.)

## Mapping: OTel attribute to Nexus field

Attribute names are the current ones at the pinned commit; the next section lists
the legacy names accepted in their place.

### Span envelope

| OTLP | Nexus `Span` field | Notes |
| --- | --- | --- |
| `traceId`, `spanId` | `trace_id`, `span_id` | Lowercase hex. 16 and 8 bytes, nonzero, else HTTP 400. |
| `parentSpanId` | `parent_span_id` | Hex; absent or all-zero is `None`. |
| `gen_ai.agent.name`, else resource `service.name`, else `otel-agent` | `agent_name` | A span never inherits another span's agent name. |
| `gen_ai.operation.name` | `span_type` | See the operation table below. |
| `startTimeUnixNano` | `client_timestamp` | UTC, exact integer arithmetic, rounded to the nearest microsecond. Original nanoseconds stay in `metadata["otel.span"]`. |
| `endTimeUnixNano - startTimeUnixNano` | `duration_ms` | `ns / 1_000_000` as a float. End before start is rejected (400). |
| collector clock | `server_timestamp` | Set by the existing publisher. |
| `error.type`, else `exception.type` of an `exception` event, else `OTelError` when status is ERROR | `error_type` | |
| status message, else `exception.message` | `error_message` | |
| resource `deployment.environment.name`, else `deployment.environment`, else `development` | `environment` | |
| resource `telemetry.sdk.version`, else `otel` | `sdk_version` | Identity only; no detector reads it. |

### `gen_ai.operation.name` to `span_type`

| Operation | `span_type` |
| --- | --- |
| `chat`, `text_completion`, `generate_content`, `embeddings`, `realtime_inference`, `fetch_response` | `llm_call` |
| `execute_tool` | `tool_call` |
| `invoke_agent`, `create_agent`, `plan`, `invoke_workflow`, `invoke_runner` | `agent_step` |
| `retrieval` | `retrieval` |
| `search_memory` | `memory_read` |
| `create_memory`, `update_memory`, `upsert_memory`, `delete_memory`, `create_memory_store`, `delete_memory_store` | `memory_write` |
| anything else or missing (HTTP, DB, `user_speech`, ...) | `custom` |

### Content: `input` and `output`

First match wins, current names before legacy ones, span attributes before span events.

| Direction | Source, in order | Nexus field |
| --- | --- | --- |
| Input | `gen_ai.tool.call.arguments` | `input` |
| Input | `gen_ai.system_instructions` (+ `gen_ai.input.messages`) | `input` |
| Input | `gen_ai.retrieval.query.text`, `gen_ai.memory.query.text` | `input` |
| Input | legacy `gen_ai.prompt`, then `gen_ai.prompt.N.content` | `input` |
| Input | events, see the alias table | `input` |
| Output | `gen_ai.tool.call.result` | `output` |
| Output | `gen_ai.output.messages` | `output` |
| Output | `gen_ai.memory.records`, `gen_ai.retrieval.documents` | `output` |
| Output | legacy `gen_ai.completion`, then `gen_ai.completion.N.content` | `output` |
| Output | events, see the alias table | `output` |

How message structures become text (`input`/`output` are text fields):

- **Text-only messages project to plain text.** A single message becomes its text
  with no wrapper, so the same prompt gives the same `input` as a native
  `@nexus.trace` span would. Several messages become `role: text` lines, one per
  message. Several text parts of one message are joined with a newline.
- `gen_ai.system_instructions` counts as a leading `system` message. System
  instructions alone become the `input`.
- **Anything non-text stays JSON.** If any part is `tool_call`,
  `tool_call_response`, `blob`, `uri`, `file`, `reasoning` or other non-text, the
  whole structure is serialized to JSON unchanged, so no information is lost and
  nothing is guessed at.
- Structured `AnyValue` content (an array of key-value lists, what a non-Python
  SDK sends) and JSON-string content (what the Python SDK sends, since it cannot
  hold nested maps) project identically. A value that is not JSON is kept verbatim.
- Content is never truncated, fetched from `*_ref` URIs, or synthesized.
- The structured original is always still in `metadata["otel.attributes"]`.

### Convenience metadata

All additive; the original attributes are never removed.

| OTel attribute | `metadata` key | Why |
| --- | --- | --- |
| `gen_ai.tool.name` | `tool_name` | Loop and misfire rules group by it. |
| `gen_ai.request.model` | `model` | Used in the classifier's span feature string. |
| `gen_ai.provider.name` | `provider` | |
| `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | `input_tokens`, `output_tokens` | |
| (their numeric sum) | `tokens_used` | Used in the classifier's span feature string. |
| `nexus.agent.role` | `role` | **Nexus extension** (semconv has no plan). PLAN_DRIFT reads `role == "planner"` on an agent span. Without the plan attributes PLAN_DRIFT cannot fire on OTLP traces. |
| `nexus.agent.plan_steps` | `plan_steps` | **Nexus extension.** String array (a JSON-array string or one step is accepted): the tools the planner declared. |
| any `nexus.*` attribute (span, or resource; span wins) | same key | The namespace Nexus owns. `nexus.synthetic` must be a **boolean** `true` to suppress alerts (a string `"true"` is not the flag). |
| derived | `nexus.content_missing` | `true` when a `gen_ai` span has neither input nor output content. Never set on `custom` spans. |
| derived | `nexus.content_refs` | The `*_ref` URIs, when content was stored externally. |
| derived | `otel.legacy_aliases` | `{legacy name: current name}` for each alias applied. |

## Alias table: legacy forms that are still emitted

Real instrumentations still emit the pre-1.37 conventions. (`opentelemetry-instrumentation-openai-v2`
2.4b0 defaults to semantic-conventions v1.30.0 until
`OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` is set.) **The current
name always wins when both are present**, and the raw legacy attribute is kept in
`metadata["otel.attributes"]`.

| Legacy | Current | Notes |
| --- | --- | --- |
| `gen_ai.system` | `gen_ai.provider.name` | Values renamed too: `vertex_ai` to `gcp.vertex_ai`, `gemini` to `gcp.gemini`, `az.ai.inference` to `azure.ai.inference`, `az.ai.openai` to `azure.ai.openai`. Other values pass through. Applies only when it came from `gen_ai.system`. |
| `gen_ai.usage.prompt_tokens` | `gen_ai.usage.input_tokens` | Mixed forms combine: current input tokens with legacy completion tokens still sum into `tokens_used`. |
| `gen_ai.usage.completion_tokens` | `gen_ai.usage.output_tokens` | |
| `gen_ai.prompt` (string) | `gen_ai.input.messages` | Used only when no current input content exists. |
| `gen_ai.completion` (string) | `gen_ai.output.messages` | Likewise. |
| `gen_ai.prompt.N.role` / `.content` (indexed, OpenLLMetry style) | `gen_ai.input.messages` | Joined in index order, `role: text`. `gen_ai.prompt.name`/`.version`/`.variable.*` are *current* prompt-template attributes, not these. |
| `gen_ai.completion.N.role` / `.content` | `gen_ai.output.messages` | |
| span events `gen_ai.system.message`, `gen_ai.user.message`, `gen_ai.assistant.message`, `gen_ai.tool.message` (pre-1.37 per-message events) | `gen_ai.system_instructions` / `gen_ai.input.messages` | Payload from the event's `content` (and `role`) attributes, or from the JSON blob in `gen_ai.event.content` that some SDKs write. A message with only `tool_calls` uses those as JSON text. Events keep their order and become `role: text` lines. |
| span event `gen_ai.choice` | `gen_ai.output.messages` | `message` (JSON string or key-value list) or the `gen_ai.event.content` blob; `content`, else `tool_calls`. |
| span event `gen_ai.client.inference.operation.details` carrying `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions` | the same attributes | The current conventions' event form, when written as a *span* event. |
| `gen_ai.input.messages.ref`, `gen_ai.output.messages.ref`, `gen_ai.system_instructions.ref` | `..._ref` | Dotted `.ref` form (older Python util-genai); both recorded in `nexus.content_refs`. |

Per-message events only reach Nexus when the instrumentation attaches them as
**span events**. Some (the OpenAI Python instrumentation's legacy path among them)
emit them as OTel **log records**, which this traces-only endpoint cannot receive;
for those, turn on span-attribute content as described above.

## Not supported

Retained verbatim in `metadata["otel.attributes"]`, not projected to a Nexus field
or used by a detector:

- `gen_ai.input.messages_ref`, `gen_ai.output.messages_ref`, `gen_ai.system_instructions_ref`,
  `gen_ai.tool.definitions_ref`: content stored externally is **not fetched**.
  The span is flagged `nexus.content_missing` and the URIs are recorded.
- `gen_ai.tool.definitions`, `gen_ai.prompt.name`, `gen_ai.prompt.version`,
  `gen_ai.prompt.variable.*`, `gen_ai.request.*` (temperature, top_p, max_tokens, ...),
  `gen_ai.response.*` (id, model, finish reasons, status, time to first chunk),
  `gen_ai.conversation.id`, `gen_ai.agent.id`/`.description`/`.version`,
  `gen_ai.main_agent.*`, `gen_ai.data_source.id`, `gen_ai.embeddings.dimension.count`,
  `gen_ai.output.type`, `gen_ai.retrieval.top_k`, `gen_ai.memory.store.id`/`record.id`/`record.count`,
  `gen_ai.skill.*`, token breakdowns (`gen_ai.usage.cache_*`, `reasoning`, per-modality).
- `gen_ai.transfer.mode`/`gen_ai.transfer.target.name` (agent handoffs): no `agent_handoff`
  mapping; the span maps by its operation name only.
- Realtime sessions (`gen_ai.realtime_session.id`, the `user_speech` operation): `custom`.
- The `gen_ai.evaluation.result` event and every other span event not listed above
  (only kept as `metadata["otel.span"]["events"]`).
- Metrics, logs and gRPC OTLP: no endpoint. The `gen_ai.client.*` metrics never arrive.
- Memory-operation tool names: there is no semconv attribute for them, so a native
  `memory_read` span's `metadata["tool_name"]` has no OTLP counterpart (see limits).
- OTLP attribute types other than the scalar, array, key-value-list and bytes `AnyValue`
  kinds (bytes become `{"base64": ...}`).

## Provenance

All span attributes live in `metadata["otel.attributes"]`. All resource
attributes live in `metadata["otel.resource"]`; instrumentation scope,
including its attributes, lives in `metadata["otel.scope"]`. The original
span protobuf JSON projection, including its name, kind, flags, trace state,
attributes, events, links, status and nanosecond times, lives in
`metadata["otel.span"]`. Its byte ID fields use protobuf JSON base64, while
Nexus top-level IDs use hex. `metadata["otel.schema_url"]` uses the scope
schema URL, falling back to the resource schema URL.

AnyValue scalar types and nested arrays/key-value lists are decoded; byte
values are represented as `{"base64": "..."}`. No unmapped attribute is dropped.
Arbitrary application attributes are not aliased into detector-specific metadata.

## Behaviour that differs from a native `@nexus.trace` trace

These are properties of OTLP, measured in [`reports/phase6/otel.md`](../reports/phase6/otel.md):

- **Trace completion has no explicit signal.** Native spans do not carry
  `metadata.final` either, so both paths complete a trace after 30 seconds without
  a new span (`TraceBuffer` timeout). An OTLP trace therefore reaches the
  classifier about 30 seconds after its last span. Spans arriving after that are
  dropped as late spans.
- **Order.** `TraceBuffer` orders by start time (`client_timestamp`) and keeps
  arrival order for equal start times. Spans exported in end order (children
  first) are therefore re-ordered by start; spans with identical start times are
  not reordered.
- **Duration precision.** OTLP times are integer nanoseconds, so a native
  `duration_ms` with sub-nanosecond float noise (for example `0.025200002710334957`)
  comes back as `0.0252`. Classifier features print `duration_ms` as text.
- **Arbitrary metadata.** Native `metadata` keys other than the ones in the table
  above (for example `cached`) have no semconv name. An instrumentation emits
  them as custom attributes, and they stay in `metadata["otel.attributes"]`, not
  as top-level metadata keys. The two the detectors read are the exception:
  `nexus.agent.role` and `nexus.agent.plan_steps` (table above). Measured on DEV
  (`reports/phase6/otel.md`): an application that emits the plan as ordinary
  `app.*` attributes loses PLAN_DRIFT on every one of the 24 DEV PLAN_DRIFT traces.
- **Memory-operation tool names.** `search_memory` has no tool-name attribute, so the
  `tool_name` of a memory read is the span type on the OTLP path. The loop and misfire
  rules group by it; no DEV trace changed classification because of this (130 spans differ).
- **`sdk_version`** is the OTel resource's `telemetry.sdk.version` (or `otel`).

## Tests

- `tests/unit/collector/test_otlp.py`: real OTel SDK tracer through the receiver, JSON and protobuf, gzip, validation and failure modes.
- `tests/unit/collector/test_otlp_semconv.py`: pinned versions, every alias in the table above, content projection, the missing-content flag, `nexus.*` promotion, and that importing the base SDK pulls in no OpenTelemetry or protobuf module.
- `tests/integration/test_otlp_exporter_interop.py`: the official `opentelemetry-exporter-otlp-proto-http` over a real loopback HTTP connection into the collector container, then Kafka, the assembler and the classifier.
- `scripts/phase6/otel_fixtures.py` and `scripts/phase6/otel_parity.py`: DEV-only parity against the native path.
