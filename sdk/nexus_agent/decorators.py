"""Instrumentation surface: @trace decorator, span() context manager, and the
explicit start_span/end_span helpers.

Nexus is never in the execution path of the user's function — it only wraps the
call to capture timing, output, and exceptions. User exceptions always
propagate (after being recorded); Nexus's own failures never do.
"""

from __future__ import annotations

import asyncio
import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from nexus_agent import client as _client_mod
from nexus_agent.client import (
    NexusClient,
    _current_span_id,
    _current_trace_id,
    new_span_id,
    new_trace_id,
)
from nexus_agent.models import SpanType


def _get_client() -> NexusClient | None:
    import nexus_agent

    return nexus_agent.get_client()


def _capture_input(args: tuple, kwargs: dict, limit: int) -> str:
    parts = [_client_mod.to_text(a, limit) for a in args]
    parts += [f"{k}={_client_mod.to_text(v, limit)}" for k, v in kwargs.items()]
    return ", ".join(parts)[:limit]


def _capture_value(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return _client_mod.to_text(value, limit)


def _split_kwargs(extra: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """agent_name is a first-class Span field; everything else is metadata."""
    md = dict(extra)
    agent_name = md.pop("agent_name", None)
    return agent_name, md


def trace(span_type: SpanType | str | Callable = SpanType.CUSTOM, **extra: Any) -> Callable:
    """Decorator that records a span for the wrapped function.

    Works both bare and with arguments::

        @nexus.trace
        def step(x): ...

        @nexus.trace(span_type="llm_call", model="gemini-3.5-flash-lite")
        def call_llm(prompt: str) -> str: ...
    """
    if callable(span_type) and not isinstance(span_type, str):
        # Bare ``@nexus.trace``: the function itself was passed as span_type.
        return trace(SpanType.CUSTOM, **extra)(span_type)

    agent_name, base_md = _split_kwargs(extra)

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                client = _get_client()
                if client is None:
                    return await fn(*args, **kwargs)
                ctx = _enter(client, span_type, base_md, agent_name, args, kwargs)
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    _exit(client, ctx, output=None, exc=exc)
                    raise
                _exit(client, ctx, output=result, exc=None)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            client = _get_client()
            if client is None:
                return fn(*args, **kwargs)
            ctx = _enter(client, span_type, base_md, agent_name, args, kwargs)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                _exit(client, ctx, output=None, exc=exc)
                raise
            _exit(client, ctx, output=result, exc=None)
            return result

        return sync_wrapper

    return decorator


def _enter(
    client: NexusClient,
    span_type: SpanType | str,
    base_md: dict[str, Any],
    agent_name: str | None,
    args: tuple,
    kwargs: dict,
) -> dict[str, Any]:
    trace_id = _current_trace_id.get() or new_trace_id()
    parent = _current_span_id.get()
    span_id = new_span_id()
    return {
        "span_type": span_type,
        "trace_id": trace_id,
        "parent_span_id": parent,
        "span_id": span_id,
        "agent_name": agent_name,
        "metadata": dict(base_md),
        "input": _capture_input(args, kwargs, client.config.max_input_chars),
        "start": time.perf_counter(),
        "tok_trace": _current_trace_id.set(trace_id),
        "tok_span": _current_span_id.set(span_id),
    }


def _exit(client: NexusClient, ctx: dict[str, Any], output: Any, exc: Exception | None) -> None:
    # Restore context first so a failure in recording can't corrupt it.
    _current_span_id.reset(ctx["tok_span"])
    _current_trace_id.reset(ctx["tok_trace"])
    duration_ms = (time.perf_counter() - ctx["start"]) * 1000.0
    span = client.build_span(
        span_type=ctx["span_type"],
        span_id=ctx["span_id"],
        trace_id=ctx["trace_id"],
        parent_span_id=ctx["parent_span_id"],
        input_text=ctx["input"],
        output_text=None if exc is not None else output,
        duration_ms=duration_ms,
        error_type=exc.__class__.__name__ if exc else None,
        error_message=str(exc) if exc else None,
        agent_name=ctx["agent_name"],
        metadata=ctx["metadata"],
    )
    client.record(span)


class SpanHandle:
    """Mutable handle yielded by the span() context manager."""

    def __init__(self) -> None:
        self.output: Any = None
        self.metadata: dict[str, Any] = {}
        self.error_type: str | None = None
        self.error_message: str | None = None

    def set_output(self, output: Any) -> None:
        self.output = output

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)


@contextmanager
def span(
    span_type: SpanType | str = SpanType.CUSTOM,
    input: Any = None,  # noqa: A002 - mirrors the Span.input field name
    **extra: Any,
) -> Iterator[SpanHandle]:
    """Context manager instrumentation::

    with nexus.span("memory_read", input=key, store="user_context") as s:
        result = memory.get(key)
        s.set_output(result)   # or: s.output = result
    """
    client = _get_client()
    handle = SpanHandle()
    if client is None:
        yield handle
        return

    agent_name, base_md = _split_kwargs(extra)
    trace_id = _current_trace_id.get() or new_trace_id()
    parent = _current_span_id.get()
    span_id = new_span_id()
    tok_trace = _current_trace_id.set(trace_id)
    tok_span = _current_span_id.set(span_id)
    start = time.perf_counter()
    exc: Exception | None = None
    try:
        yield handle
    except Exception as e:  # noqa: BLE001
        exc = e
        raise
    finally:
        _current_span_id.reset(tok_span)
        _current_trace_id.reset(tok_trace)
        duration_ms = (time.perf_counter() - start) * 1000.0
        md = dict(base_md)
        md.update(handle.metadata)
        built = client.build_span(
            span_type=span_type,
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent,
            input_text=_capture_value(input, client.config.max_input_chars),
            output_text=None if exc is not None else handle.output,
            duration_ms=duration_ms,
            error_type=(exc.__class__.__name__ if exc else handle.error_type),
            error_message=(str(exc) if exc else handle.error_message),
            agent_name=agent_name,
            metadata=md,
        )
        client.record(built)
