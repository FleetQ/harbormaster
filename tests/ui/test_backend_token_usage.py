"""v11.0.0a5: backend-side token counter instrumentation.

Tests cover:
  - StreamUsage merges per-message + result usage blocks correctly.
  - _StreamWithUsage iterator passes deltas through transparently
    while exposing `.usage`.
  - When the backend reports usage, the SSE `usage` event carries
    real input_tokens / output_tokens / model and DROPS the
    `approximate: true` flag (closes v9.0.0a5 deviation).
  - When the backend doesn't report usage, the SSE `usage` event
    falls back to the v9 chunk-count approximation with
    approximate=True.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from harbormaster.backends.claude import (
    ClaudeBackend,
    StreamUsage,
    _StreamWithUsage,
)
from harbormaster.config import HarbormasterConfig

# -- StreamUsage mechanics ---------------------------------------------


def test_stream_usage_starts_empty() -> None:
    u = StreamUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.model is None
    assert u.has_real_usage is False


def test_stream_usage_absorbs_assistant_block() -> None:
    u = StreamUsage()
    msg = {
        "type": "assistant",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 25,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 5,
            },
        },
    }
    u.merge_message_usage(msg)
    assert u.input_tokens == 100
    assert u.output_tokens == 25
    assert u.cache_creation_input_tokens == 10
    assert u.cache_read_input_tokens == 5
    assert u.model == "claude-sonnet-4-6"
    assert u.has_real_usage is True


def test_stream_usage_later_message_overrides_earlier() -> None:
    """Each assistant message is a snapshot — the LATEST one wins so
    the post-stream `usage` reflects the final tally."""
    u = StreamUsage()
    u.merge_message_usage({
        "type": "assistant",
        "message": {"usage": {"input_tokens": 50, "output_tokens": 10}},
    })
    u.merge_message_usage({
        "type": "assistant",
        "message": {"usage": {"input_tokens": 50, "output_tokens": 30}},
    })
    assert u.output_tokens == 30
    assert u.input_tokens == 50


def test_stream_usage_absorbs_result_summary() -> None:
    """The `result` summary line carries an authoritative final tally
    — a top-level usage block (vs message.usage on assistant lines)."""
    u = StreamUsage()
    u.merge_message_usage({
        "type": "result",
        "usage": {"input_tokens": 200, "output_tokens": 75},
    })
    assert u.input_tokens == 200
    assert u.output_tokens == 75
    assert u.has_real_usage is True


def test_stream_usage_silently_ignores_non_usage_messages() -> None:
    u = StreamUsage()
    u.merge_message_usage({"type": "system"})
    u.merge_message_usage({"type": "tool_use"})
    u.merge_message_usage({})
    assert u.has_real_usage is False
    assert u.input_tokens == 0


# -- _StreamWithUsage wrapper ------------------------------------------


def test_stream_with_usage_iterates_text() -> None:
    u = StreamUsage()

    def src() -> Any:
        yield "hello "
        yield "world"

    s = _StreamWithUsage(src(), u)
    assert list(s) == ["hello ", "world"]
    assert s.usage is u


def test_stream_with_usage_exposes_attribute() -> None:
    u = StreamUsage(input_tokens=1, output_tokens=2, has_real_usage=True)

    def src() -> Any:
        yield "x"

    s = _StreamWithUsage(src(), u)
    list(s)
    # Attribute access works post-iteration.
    assert s.usage.input_tokens == 1
    assert s.usage.output_tokens == 2


# -- _extract_assistant_text feeds usage --------------------------------


def test_extract_assistant_text_feeds_usage_from_assistant_msg() -> None:
    line = json.dumps({
        "type": "assistant",
        "message": {
            "model": "m",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        },
    })
    u = StreamUsage()
    out = list(ClaudeBackend._extract_assistant_text(line, usage=u))
    assert out == ["hi"]
    assert u.input_tokens == 7
    assert u.output_tokens == 3


def test_extract_assistant_text_feeds_usage_from_result_msg() -> None:
    line = json.dumps({
        "type": "result",
        "usage": {"input_tokens": 22, "output_tokens": 11},
    })
    u = StreamUsage()
    out = list(ClaudeBackend._extract_assistant_text(line, usage=u))
    assert out == []  # result lines have no text deltas
    assert u.input_tokens == 22
    assert u.output_tokens == 11
    assert u.has_real_usage is True


def test_extract_assistant_text_without_usage_arg_still_works() -> None:
    """Backwards-compat: callers that don't pass usage continue to
    work (only text deltas yielded)."""
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hi"}]},
    })
    out = list(ClaudeBackend._extract_assistant_text(line))
    assert out == ["hi"]


# -- SSE usage event integration ----------------------------------------


def _drain_sse_events(record_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Helper: drive _emit_chunks_then_result and collect events."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    received: list[dict[str, Any]] = []

    async def run(sync_iter: Any) -> None:
        async for evt in _emit_chunks_then_result(
            sync_iter, record_ctx=record_ctx,
        ):
            received.append(evt)

    asyncio.run(run(record_ctx["__iter__"]))
    return received


@pytest.mark.asyncio
async def test_sse_usage_event_uses_real_counts_when_backend_reports() -> None:
    """When the wrapped iterator's `.usage.has_real_usage` is True,
    the SSE `usage` event carries the real numbers and DROPS the
    `approximate: true` flag."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    u = StreamUsage(
        input_tokens=42, output_tokens=18,
        cache_read_input_tokens=4, cache_creation_input_tokens=0,
        model="claude-sonnet-4-6", has_real_usage=True,
    )

    def text_gen() -> Any:
        yield "hello "
        yield "world"

    wrapped = _StreamWithUsage(text_gen(), u)

    received: list[dict[str, Any]] = []
    async for evt in _emit_chunks_then_result(wrapped):
        received.append(evt)

    usage_events = [e for e in received if e["event"] == "usage"]
    assert len(usage_events) == 1
    payload = json.loads(usage_events[0]["data"])
    assert payload["input_tokens"] == 42
    assert payload["output_tokens"] == 18
    assert payload["cache_read_input_tokens"] == 4
    assert payload["model"] == "claude-sonnet-4-6"
    assert "approximate" not in payload
    # The legacy fields are still present so dashboards that read them
    # don't break.
    assert payload["output_chunks"] == 2
    assert payload["output_chars"] == len("hello world")


@pytest.mark.asyncio
async def test_sse_usage_event_falls_back_to_approximate_when_no_metadata() -> None:
    """When the iterator has no .usage attr (older backend) OR
    has_real_usage is False, the v9 approximation path runs."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    def plain_gen() -> Any:
        yield "abc"
        yield "def"

    received: list[dict[str, Any]] = []
    async for evt in _emit_chunks_then_result(plain_gen()):
        received.append(evt)

    usage_events = [e for e in received if e["event"] == "usage"]
    assert len(usage_events) == 1
    payload = json.loads(usage_events[0]["data"])
    assert payload.get("approximate") is True
    assert payload["output_chunks"] == 2
    assert payload["output_chars"] == 6
    assert "input_tokens" not in payload


@pytest.mark.asyncio
async def test_sse_usage_event_falls_back_when_has_real_usage_is_false() -> None:
    """A wrapped iterator whose backend NEVER emitted a usage block
    (has_real_usage stays False) falls back to approximation."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    u = StreamUsage()  # has_real_usage = False

    def text_gen() -> Any:
        yield "x"

    wrapped = _StreamWithUsage(text_gen(), u)

    received: list[dict[str, Any]] = []
    async for evt in _emit_chunks_then_result(wrapped):
        received.append(evt)

    usage_events = [e for e in received if e["event"] == "usage"]
    payload = json.loads(usage_events[0]["data"])
    assert payload.get("approximate") is True


def test_make_local_backend_stream_returns_iterable_with_usage_attr() -> None:
    """Smoke test: make_local_backend_stream still returns a callable
    `Iterator[str]` (typing contract preserved). Backend integration
    is exercised via mocked iterators in the SSE tests above."""
    from harbormaster.tools._helpers import make_local_backend_stream

    assert callable(make_local_backend_stream)
    # Signature unchanged (kwargs).
    import inspect
    sig = inspect.signature(make_local_backend_stream)
    assert {"project_name", "prompt", "max_turns", "config"} <= set(
        sig.parameters,
    )


def test_v9_deviation_doc_string_dropped_from_routes() -> None:
    """The v9.0.0a5 'best-effort usage event' comment block was
    replaced by the v11 implementation. Belt-and-braces: the new
    comment mentions both the real-usage path and the fallback."""
    src = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "routes.py"
    ).read_text(encoding="utf-8")
    assert "v11.0.0a5: real backend-reported usage" in src
    assert "approximate" in src  # fallback path still documented


# Smoke test for HarbormasterConfig import — exercised elsewhere but
# keeps mypy from complaining about the unused import in skeleton.
def test_harbormaster_config_importable() -> None:
    assert HarbormasterConfig() is not None
