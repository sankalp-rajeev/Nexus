# Plain OpenTelemetry to Nexus

An agent that uses **only the OpenTelemetry SDK and the OTLP/HTTP exporter**. There is
no `nexus` import and no Nexus SDK: the spans follow the OpenTelemetry GenAI semantic
conventions and Nexus ingests them at its OTLP endpoint (`POST /v1/traces`).

`run_demo.py` has a `fake_llm` function that emits what a GenAI instrumentation would
emit, with no provider call: `chat` spans with `gen_ai.request.model`, token usage and
(when content capture is on) `gen_ai.system_instructions`, `gen_ai.input.messages`
and `gen_ai.output.messages`, plus `execute_tool` spans with `gen_ai.tool.call.arguments`
and `gen_ai.tool.call.result`, all under an `invoke_agent` root.

```powershell
pip install -r examples/otel_plain/requirements.txt

# Nexus stack with the collector, assembler and classifier running (see docs/otel_mapping.md)
python examples/otel_plain/run_demo.py --scenario loop --synthetic
python examples/otel_plain/run_demo.py --scenario normal --synthetic
python examples/otel_plain/run_demo.py --scenario normal --no-content --synthetic
```

`--synthetic` adds the boolean attribute `nexus.synthetic=true` to every span, which makes
the classifier classify the trace but never raise an alert (so a paid critic can never be
triggered by a demo). Leave it off to see a real alert for the `loop` scenario.

The collector address comes from `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (default
`http://127.0.0.1:8000/v1/traces`).

## Content capture decides what Nexus can see

The fake instrumentation honors the same switch real ones do: it records prompt and
response text only when `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=span_only`
(the script sets that unless you pass `--no-content`). Nexus's detectors read that text.
Without it the spans still arrive and are classified from their structure, but each one is
flagged `nexus.content_missing=true`. See [docs/otel_mapping.md](../../docs/otel_mapping.md)
for what degrades.

## See the trace reach Nexus

A trace is complete 30 seconds after its last span (Nexus's inactivity timeout), then it is
assembled into Postgres and classified.

```powershell
# classification (Kafka)
docker exec nexus-phase6-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh `
  --bootstrap-server localhost:9092 --topic nexus.spans.classified --from-beginning --timeout-ms 8000

# assembled spans (Postgres), using the trace_id the script printed
docker exec nexus-phase6-postgres-1 psql -U nexus -d nexus -c `
  "select span_type, left(input,48) input, left(output,40) output from spans where trace_id='<trace_id>' order by client_timestamp"
```

The looping scenario repeats the same `lookup` call three times; the classifier's loop rule
reports `LOOP_DETECTED`. The output of an actual run is in
[`reports/phase6/otel.md`](../../reports/phase6/otel.md).

## Real auto-instrumentation (documentation only, not run here)

Nothing below was executed in this step (it would call a real model provider). It shows
how the same endpoint is used by an unmodified application with a GenAI instrumentation
package:

```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp-proto-http \
            opentelemetry-instrumentation-openai-v2

export OTEL_SERVICE_NAME=my-agent
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8000/v1/traces

# current GenAI names, and prompt/response content recorded on the spans
export OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=span_only

# Nexus has no metrics or logs endpoint
export OTEL_METRICS_EXPORTER=none
export OTEL_LOGS_EXPORTER=none

opentelemetry-instrument python my_agent.py
```

Use `span_only` (or `span_and_event`), not `event_only`: events are sent as log records and
never reach a traces-only endpoint. The variable's name and values depend on the
instrumentation version; check its README.
