"""v9.0.0a5: typed SSE events alongside legacy `chunk`.

Closes the v7-deferred item "Typed SSE events". The chunk pipeline
that powers ask_project / delegate_task / fan_out_ask now emits:

  * `chunk` (legacy) — `{text: <str>}` — DEPRECATED, removed in v10
  * `token` (new)    — `{delta: <str>}` — typed text delta
  * `usage` (new)    — best-effort output counts before `result`
  * `result` (existing) — final assembled MCP envelope
  * `error` (existing) — failure envelope

Backwards compat: clients that only listen for `chunk` continue to
work unchanged. Clients that listen for `token` are expected to
ignore `chunk` (the v9.0.0a5 askForm script enforces this with a
`preferTokenEvents` flag).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from harbormaster.ui.routes import _emit_chunks_then_result


def _drive(iterable: object) -> list[dict[str, str]]:
    async def collect() -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        async for ev in _emit_chunks_then_result(iterable):
            out.append(ev)
        return out

    return asyncio.run(collect())


def test_two_chunks_emit_both_chunk_and_token_events() -> None:
    """Each text delta must yield ONE `chunk` event AND ONE `token` event."""
    def fake_iter() -> object:
        yield "hello "
        yield "world"

    events = _drive(fake_iter())
    kinds = [ev["event"] for ev in events]
    # Order: chunk, token, chunk, token, usage, result.
    assert kinds == ["chunk", "token", "chunk", "token", "usage", "result"]


def test_chunk_event_carries_text_field() -> None:
    """Backwards-compat: legacy clients reading `text` keep working."""
    def fake_iter() -> object:
        yield "hi"

    events = _drive(fake_iter())
    chunk_event = next(ev for ev in events if ev["event"] == "chunk")
    payload = json.loads(chunk_event["data"])
    assert payload == {"text": "hi"}


def test_token_event_carries_delta_field() -> None:
    """v9.0.0a5: typed token event uses `delta`, not `text`."""
    def fake_iter() -> object:
        yield "hi"

    events = _drive(fake_iter())
    token_event = next(ev for ev in events if ev["event"] == "token")
    payload = json.loads(token_event["data"])
    assert payload == {"delta": "hi"}


def test_usage_event_emitted_before_result() -> None:
    """The `usage` event MUST land just before `result`."""
    def fake_iter() -> object:
        yield "a"
        yield "b"
        yield "c"

    events = _drive(fake_iter())
    usage_idx = next(i for i, ev in enumerate(events) if ev["event"] == "usage")
    result_idx = next(i for i, ev in enumerate(events) if ev["event"] == "result")
    assert usage_idx < result_idx, "usage must precede result"
    assert result_idx - usage_idx == 1, "usage must be immediately before result"


def test_usage_event_carries_output_counts() -> None:
    def fake_iter() -> object:
        yield "abc"
        yield "de"

    events = _drive(fake_iter())
    usage = next(ev for ev in events if ev["event"] == "usage")
    payload = json.loads(usage.data) if hasattr(usage, "data") else json.loads(usage["data"])
    assert payload["output_chunks"] == 2
    assert payload["output_chars"] == 5
    assert payload["approximate"] is True


def test_token_and_chunk_share_same_text() -> None:
    """For each delta, the chunk's text and the token's delta MUST match."""
    def fake_iter() -> object:
        yield "alpha"
        yield "beta"

    events = _drive(fake_iter())
    pairs: list[tuple[str, str]] = []
    pending_chunk: str | None = None
    for ev in events:
        if ev["event"] == "chunk":
            pending_chunk = json.loads(ev["data"])["text"]
        elif ev["event"] == "token":
            assert pending_chunk is not None
            pairs.append((pending_chunk, json.loads(ev["data"])["delta"]))
            pending_chunk = None
    assert pairs == [("alpha", "alpha"), ("beta", "beta")]


def test_every_event_carries_monotonic_id() -> None:
    """v9.0.0a4 contract preserved: per-stream monotonic ids."""
    def fake_iter() -> object:
        yield "x"

    events = _drive(fake_iter())
    ids = [int(ev["id"]) for ev in events]
    assert ids == sorted(ids)
    assert ids[0] == 1
    assert len(set(ids)) == len(ids), "ids must be unique"


def test_error_path_does_not_emit_token_or_usage() -> None:
    """When BackendError raises mid-iteration, only the error event
    is emitted (no usage / no result). Backwards compat with v9.0.0a4."""
    from harbormaster.backends.base import BackendError

    def fake_iter() -> object:
        yield "first"
        raise BackendError("config_error", "missing key")

    events = _drive(fake_iter())
    kinds = [ev["event"] for ev in events]
    # Got chunk + token from the first delta, then immediately errored.
    assert "error" in kinds
    assert "usage" not in kinds
    assert "result" not in kinds


# -- template assertions ------------------------------------------------


def test_ask_form_script_handles_token_event() -> None:
    """The Alpine consumer in _ask_form_script.html must reference the
    new `token` event. Pin the literal so future refactors don't drop
    the migration."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_ask_form_script.html"
    ).read_text()
    assert "ev.event === 'token'" in src
    assert "preferTokenEvents" in src
    assert "ev.event === 'usage'" in src
    assert "ev.event === 'tool'" in src


def test_ask_form_script_keeps_legacy_chunk_handler() -> None:
    """Backwards-compat sentinel: the legacy `chunk` handler is still
    present (will be removed in v10 alongside the server-side emit)."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_ask_form_script.html"
    ).read_text()
    assert "ev.event === 'chunk'" in src
