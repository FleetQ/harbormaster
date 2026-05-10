"""v9.0.0a5: typed SSE events alongside legacy `chunk`.
v10.0.0a2: legacy `chunk` event removed; only `token` is emitted.

The chunk pipeline that powers ask_project / delegate_task /
fan_out_ask now emits:

  * `token`  — `{delta: <str>}` — typed text delta (the only delta event)
  * `usage`  — best-effort output counts before `result`
  * `result` — final assembled MCP envelope
  * `error`  — failure envelope

Backwards-compat cycle was one minor version (deprecated v9.0.0a5,
removed v10.0.0a2). Clients that still listen for `chunk` will get
nothing — they must migrate to `token` (data.delta).
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


def test_two_deltas_emit_only_token_events() -> None:
    """v10.0.0a2: each text delta yields ONE `token` event (no `chunk`)."""
    def fake_iter() -> object:
        yield "hello "
        yield "world"

    events = _drive(fake_iter())
    kinds = [ev["event"] for ev in events]
    # Order: token, token, usage, result. NO chunk events.
    assert kinds == ["token", "token", "usage", "result"]


def test_chunk_event_no_longer_emitted() -> None:
    """v10.0.0a2 removal sentinel: no `chunk` event anywhere in stream."""
    def fake_iter() -> object:
        yield "a"
        yield "b"
        yield "c"

    events = _drive(fake_iter())
    kinds = [ev["event"] for ev in events]
    assert "chunk" not in kinds


def test_token_event_carries_delta_field() -> None:
    """Typed token event uses `delta`."""
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


def test_every_event_carries_monotonic_id() -> None:
    """v9.0.0a4 contract preserved: per-stream monotonic ids."""
    def fake_iter() -> object:
        yield "x"

    events = _drive(fake_iter())
    ids = [int(ev["id"]) for ev in events]
    assert ids == sorted(ids)
    assert ids[0] == 1
    assert len(set(ids)) == len(ids), "ids must be unique"


def test_error_path_does_not_emit_usage_or_result() -> None:
    """When BackendError raises mid-iteration, only the error event
    is emitted (no usage / no result). Backwards compat with v9.0.0a4."""
    from harbormaster.backends.base import BackendError

    def fake_iter() -> object:
        yield "first"
        raise BackendError("config_error", "missing key")

    events = _drive(fake_iter())
    kinds = [ev["event"] for ev in events]
    # Got token from the first delta, then immediately errored.
    assert "error" in kinds
    assert "usage" not in kinds
    assert "result" not in kinds


# -- template assertions ------------------------------------------------


def test_ask_form_script_handles_token_event() -> None:
    """The Alpine consumer in _ask_form_script.html must reference the
    `token` event. Pin the literal so future refactors don't drop
    the contract."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_ask_form_script.html"
    ).read_text()
    assert "ev.event === 'token'" in src
    assert "ev.event === 'usage'" in src
    assert "ev.event === 'tool'" in src


def test_ask_form_script_no_longer_references_chunk() -> None:
    """v10.0.0a2 removal sentinel: the legacy `chunk` event branch
    must not appear in the Alpine consumer."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_ask_form_script.html"
    ).read_text()
    assert "ev.event === 'chunk'" not in src
    assert "preferTokenEvents" not in src


def test_delegate_form_uses_token_not_chunk() -> None:
    """v10.0.0a2: delegate_form's SSE consumer also migrated to
    `token`. The legacy `chunk` branch must be gone."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "delegate_form.html"
    ).read_text()
    assert "ev.event === 'token'" in src
    assert "ev.event === 'chunk'" not in src
