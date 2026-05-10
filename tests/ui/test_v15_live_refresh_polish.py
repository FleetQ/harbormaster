"""v15.0.0a3 — SSE-driven live refresh for timeline + source dropdown.

Two v14-retro carry-overs:

* Timeline view subscribes to /api/network/stream and updates bars
  in real time without a re-fetch on toggle. DOM updates throttled
  to 1s buckets.
* Network filter dropdown live-adds new caller sources as SSE events
  arrive, with Set-based dedup.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


# -- timeline SSE-driven refresh --------------------------------


def test_network_template_timeline_uses_cache_with_1s_throttle() -> None:
    body = _read("network.html")
    # v16.0.0a1: the per-getter cache fields are gone — the shared
    # `cachedGetter` helper owns the cache slot. The 1s ttlMs +
    # ttlMs-keyed freshness check live in `_partials/_cached_getter.html`.
    assert "cachedGetter(this, 'timelineBuckets'" in body
    assert "ttlMs: 1000" in body


def test_network_template_timeline_cache_invalidates_on_window_change() -> None:
    body = _read("network.html")
    # v16.0.0a1: window-change invalidation now flows through the deps
    # tuple. `timelineWindow`, `events.length`, and `_timelineTick` are
    # all in deps — a 1h ↔ 24h flip recomputes on the next read.
    assert (
        "deps: [this.timelineWindow, this.events.length, this._timelineTick]"
        in body
    )


def test_network_template_timeline_throttle_started_in_init() -> None:
    body = _read("network.html")
    assert "_startTimelineThrottle()" in body
    # 1s setInterval bumps the tick.
    assert "setInterval(() => {" in body
    assert "this._timelineTick = (this._timelineTick + 1) % 1_000_000;" in body


def test_network_template_timeline_getter_reads_tick_for_reactivity() -> None:
    body = _read("network.html")
    # v16.0.0a1: `_timelineTick` is read inside the deps tuple passed
    # to `cachedGetter` — Alpine still tracks the read (it's a normal
    # property access on the Alpine reactive object), so the getter
    # re-runs when the 1s throttle bumper fires.
    assert "this._timelineTick" in body
    assert "deps: [this.timelineWindow, this.events.length, this._timelineTick]" in body


def test_network_template_sse_handler_pushes_to_events_unchanged() -> None:
    """The v14 SSE handler still appends to events — we did NOT
    short-circuit the re-render path."""
    body = _read("network.html")
    assert "this.events.push(ev)" in body
    assert "if (this.events.length > 500) this.events.shift()" in body


# -- network filter dropdown live-add --------------------------


def test_network_template_sse_handler_live_adds_source() -> None:
    body = _read("network.html")
    # The SSE event handler calls the live-add helper.
    assert "this._maybeAppendSourceOption(ev)" in body


def test_network_template_source_dedup_uses_set() -> None:
    body = _read("network.html")
    # Set-based dedup; no duplicate dropdown entries even under
    # back-to-back SSE events.
    assert "this._sourceOptionsSet = new Set(this.sourceOptions || [])" in body
    assert "this._sourceOptionsSet.has(src)" in body
    assert "this._sourceOptionsSet.add(src)" in body


def test_network_template_source_append_keeps_sorted_order() -> None:
    body = _read("network.html")
    # Spread + sort keeps the list deterministic.
    assert "[...this.sourceOptions, src].sort()" in body


def test_network_template_source_append_skips_empty_caller() -> None:
    body = _read("network.html")
    # Guard against empty / undefined caller field.
    assert "if (!src) return;" in body


# -- behavioural carry-over: existing v14 behaviour preserved --


def test_network_template_timeline_window_toggle_unchanged() -> None:
    body = _read("network.html")
    # Both 1h and 24h pills still wired to timelineWindow.
    assert "@click=\"timelineWindow = '1h'\"" in body
    assert "@click=\"timelineWindow = '24h'\"" in body


def test_network_template_chat_order_cache_unchanged() -> None:
    body = _read("network.html")
    # v16.0.0a1: chatOrder() now routes through the shared
    # `cachedGetter` helper. The deps-only invalidation behaviour is
    # preserved (events.length is the sole dep, no ttlMs).
    assert "cachedGetter(this, 'chatOrder'" in body
    assert "deps: [this.events.length]" in body
