# OTLP/HTTP field mapping

Implemented in `sdk/nexus_agent/integrations/otel.py` and
`services/collector/routes/otlp.py`. Reference conventions:
[GenAI client spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md),
[GenAI agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md),
and [OTLP/HTTP](https://opentelemetry.io/docs/specs/otlp/).
GenAI conventions are still in development; unsupported operations remain
`custom` and retain all original attributes.

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

## Nexus projection

- `trace_id`, `span_id`: OTLP trace/span IDs as lowercase hexadecimal strings.
  IDs must be 16/8 bytes respectively and nonzero. `parent_span_id`: hexadecimal
  parent ID; absent or all-zero parent maps to `None`.
- `agent_name`: span `gen_ai.agent.name`, then resource `service.name`, then
  `otel-agent`. A child without its own agent attribute uses the resource name;
  the adapter does not infer attributes from another span.
- `span_type`: `gen_ai.operation.name` values `chat`, `text_completion`,
  `generate_content`, `realtime_inference`, `fetch_response`, `embeddings` map
  to `llm_call`; `execute_tool` to `tool_call`; `invoke_agent`, `create_agent`,
  `plan` to `agent_step`; `retrieval` to `retrieval`; `search_memory` to
  `memory_read`; `create_memory`, `update_memory`, `upsert_memory`,
  `delete_memory`, `create_memory_store`, `delete_memory_store` to
  `memory_write`. Other/missing values map to `custom`.
- `input`: first present attribute among `gen_ai.tool.call.arguments`,
  `gen_ai.input.messages`, `gen_ai.retrieval.query.text`,
  `gen_ai.memory.query.text`, legacy `gen_ai.prompt`. Missing content is `""`.
- `output`: first present attribute among `gen_ai.tool.call.result`,
  `gen_ai.output.messages`, `gen_ai.memory.records`, legacy
  `gen_ai.completion`. Missing content is `None`.
- Content strings remain unchanged. Structured AnyValue content is serialized
  to JSON, including message roles and parts. As a compatibility fallback,
  events named `gen_ai.input.messages` / `gen_ai.output.messages` with a
  `gen_ai.messages` attribute supply the corresponding content. Other events
  remain available in raw metadata. Content is not truncated or fetched from
  external references, and no absent content is synthesized.
- `client_timestamp`: UTC start time; Python datetime precision is microseconds.
  `duration_ms`: `(endTimeUnixNano - startTimeUnixNano) / 1_000_000`.
  End-before-start spans are rejected. Exact original nanoseconds are retained
  in `metadata["otel.span"]`.
- `server_timestamp`: UTC receipt time, set by the existing collector publisher.
- `error_type`: `error.type`, then `exception.type` from an exception event,
  then `OTelError` for ERROR status. `error_message`: status message, then
  `exception.message`. Otherwise these are `None`.
- `environment`: resource `deployment.environment.name`, then legacy
  `deployment.environment`, then `development`.
- `sdk_version`: resource `telemetry.sdk.version`, then `otel`.

## Attributes and provenance

All span attributes live in `metadata["otel.attributes"]`. All resource
attributes live in `metadata["otel.resource"]`; instrumentation scope,
including its attributes, lives in `metadata["otel.scope"]`. The original
span protobuf JSON projection, including its name, kind, flags, trace state,
attributes, events, links, status and nanosecond times, lives in
`metadata["otel.span"]`. Its byte ID fields use protobuf JSON base64, while
Nexus top-level IDs use hex. `metadata["otel.schema_url"]` uses the scope
schema URL, falling back to the resource schema URL.

AnyValue scalar types and nested arrays/key-value lists are decoded; byte
values are represented as `{"base64": "..."}`. No unmapped attribute is
dropped. Convenience aliases are additive: `gen_ai.tool.name` becomes
`tool_name`; `gen_ai.request.model` becomes `model`; `gen_ai.provider.name`
becomes `provider`; input/output usage tokens become `input_tokens` and
`output_tokens`, with a numeric sum in `tokens_used`. There is no aliasing of
arbitrary application attributes into detector-specific metadata.

The interoperability test uses a real `TracerProvider`, tracer and
`SimpleSpanProcessor`, with a test exporter that serializes its actual
`ReadableSpan` objects into the official OTLP protobuf schema and POSTs
through FastAPI's in-process client. It covers JSON and protobuf with gzip,
parent IDs, timing, content, errors and preservation of custom attributes.
