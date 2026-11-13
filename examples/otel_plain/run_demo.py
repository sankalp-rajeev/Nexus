"""Plain OpenTelemetry to Nexus: GenAI spans from a fake LLM, no Nexus import.

Only ``opentelemetry-sdk`` and the OTLP/HTTP exporter are used. ``fake_llm`` stands in for a
GenAI instrumentation: it emits spans with the current semantic-convention names
(``gen_ai.operation.name``, ``gen_ai.request.model``, ``gen_ai.input.messages``, ...) and, like a
real instrumentation, records prompt/response *content* only when content capture is enabled
(``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=span_only``). No provider is called.

    python run_demo.py                  # a looping agent, content captured
    python run_demo.py --scenario normal
    python run_demo.py --no-content     # what an instrumentation sends by default
    python run_demo.py --synthetic      # mark every span nexus.synthetic=true (no alert is raised)
"""

from __future__ import annotations

import argparse
import json
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

CAPTURE_VARIABLE = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://127.0.0.1:8000/v1/traces")
MODEL = "fake-model-1"


def capture_content() -> bool:
    return os.getenv(CAPTURE_VARIABLE, "").strip().lower() in {"span_only", "span_and_event", "true"}


def text_messages(role: str, text: str, **extra) -> str:
    """Message content as the current conventions define it (a JSON string in Python OTel)."""
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}], **extra}])


def fake_llm(tracer, prompt: str, *, system: str, synthetic: bool) -> str:
    """A canned model call that emits a semconv-correct ``chat`` span."""
    reply = ("Refunds are available within 30 days of purchase." if "Tool said" in prompt
             else "I need to look up the refund policy first.")
    with tracer.start_as_current_span(f"chat {MODEL}", kind=trace.SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", "fake")
        span.set_attribute("gen_ai.request.model", MODEL)
        span.set_attribute("gen_ai.response.model", MODEL)
        span.set_attribute("gen_ai.usage.input_tokens", len(prompt.split()) + len(system.split()))
        span.set_attribute("gen_ai.usage.output_tokens", len(reply.split()))
        if capture_content():
            span.set_attribute("gen_ai.system_instructions", json.dumps([{"type": "text", "content": system}]))
            span.set_attribute("gen_ai.input.messages", text_messages("user", prompt))
            span.set_attribute("gen_ai.output.messages", text_messages("assistant", reply, finish_reason="stop"))
        if synthetic:
            span.set_attribute("nexus.synthetic", True)
    return reply


def lookup_tool(tracer, query: str, *, synthetic: bool) -> str:
    """A tool call span (``execute_tool``) over a fake knowledge base."""
    result = json.dumps({"hits": []}) if "stale" in query else json.dumps({"hits": ["Refunds within 30 days."]})
    with tracer.start_as_current_span("execute_tool lookup") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "lookup")
        if capture_content():
            span.set_attribute("gen_ai.tool.call.arguments", json.dumps({"query": query}))
            span.set_attribute("gen_ai.tool.call.result", result)
        if synthetic:
            span.set_attribute("nexus.synthetic", True)
    return result


def run_agent(tracer, scenario: str, synthetic: bool) -> str:
    """Run one agent invocation; returns its trace id (hex)."""
    system = "You are a support agent. Use the lookup tool, then answer in one sentence."
    with tracer.start_as_current_span("invoke_agent refund-agent") as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        root.set_attribute("gen_ai.agent.name", "refund-agent")
        if synthetic:
            root.set_attribute("nexus.synthetic", True)
        question = "What is the refund policy?"
        fake_llm(tracer, question, system=system, synthetic=synthetic)
        for _ in range(3 if scenario == "loop" else 1):
            # A loop repeats the very same call; a normal run does not.
            query = "stale refund policy" if scenario == "loop" else "refund policy"
            lookup_tool(tracer, query, synthetic=synthetic)
        fake_llm(tracer, f"{question} Tool said: refund policy found.", system=system, synthetic=synthetic)
    return f"{root.get_span_context().trace_id:032x}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=["loop", "normal"], default="loop")
    parser.add_argument("--no-content", action="store_true", help="do not capture prompt/response content")
    parser.add_argument("--synthetic", action="store_true", help="mark spans nexus.synthetic=true")
    args = parser.parse_args()
    if args.no_content:
        os.environ.pop(CAPTURE_VARIABLE, None)
    else:
        os.environ.setdefault(CAPTURE_VARIABLE, "span_only")
    provider = TracerProvider(resource=Resource.create({
        "service.name": "otel-plain-example", "deployment.environment.name": "example",
    }))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT, timeout=10)))
    tracer = provider.get_tracer("otel-plain-example", "1")
    trace_id = run_agent(tracer, args.scenario, args.synthetic)
    provider.force_flush()
    provider.shutdown()
    print(f"exported trace_id={trace_id} scenario={args.scenario} content_captured={capture_content()} "
          f"synthetic={args.synthetic} endpoint={ENDPOINT}")


if __name__ == "__main__":
    main()
