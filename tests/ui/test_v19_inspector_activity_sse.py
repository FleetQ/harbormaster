"""v19.0.0a7: SSE-driven activity feed in the dashboard inspector.

Pins the structural invariants of the enhanced `activityFeed()` Alpine
factory and the inspector markup that consumes it. Mirrors the pattern of
test_v19_inspector_content.py — pure template-source assertions, no live
server. Behavioural integration (initial load + live SSE prepend + 1s
batching + 1.5s pulse-then-clear) is exercised by the visual-verification
script under /tmp/v19-a7-* during release.

Why source-only:
- The factory talks to live `/api/network/stream`; spinning it up under
  pytest would couple this UI test to the SSE plumbing tested in
  test_typed_sse_events.py.
- The browser smoke (Playwright run during release) confirms EventSource
  actually opens and the live indicator paints. Tests here lock the
  contract so the smoke can keep running unchanged.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text()


def test_inspector_activity_feed_subscribes_on_init() -> None:
    """Inspector section must call subscribe() in x-init alongside the
    pre-existing load() and start() calls — without it the SSE stream
    never opens and the feed stays in poll-only mode."""
    src = _read("dashboard.html")
    assert 'x-data="activityFeed()" x-init="load(); start(); subscribe()"' in src, (
        "inspector activityFeed must wire load(); start(); subscribe() in x-init"
    )


def test_inspector_activity_feed_renders_live_indicator() -> None:
    """Live-stream indicator must be present and bound to `connected`,
    so the operator can see at a glance whether the SSE stream is open
    versus stalled in poll-only fallback."""
    src = _read("dashboard.html")
    assert "data-inspector-activity-live" in src, (
        "missing data-inspector-activity-live hook for the live indicator"
    )
    # Bound to `connected` flag (set from EventSource open/error handlers).
    assert 'x-show="connected"' in src, (
        "live indicator must be x-show='connected' so it hides when SSE drops"
    )


def test_inspector_activity_feed_view_all_link() -> None:
    """`view all →` link must point at /network so users can drill into
    the full network log when they spot something interesting in the
    inspector tail."""
    src = _read("dashboard.html")
    # Find the inspector block and assert the link lives inside it.
    inspector_idx = src.find("{% block inspector %}")
    endblock_idx = src.find("{% endblock %}", inspector_idx)
    assert inspector_idx >= 0 and endblock_idx > inspector_idx
    inspector_src = src[inspector_idx:endblock_idx]
    assert 'href="/network"' in inspector_src, (
        "inspector activity feed must link to /network for full log"
    )
    assert "view all" in inspector_src, (
        "inspector activity feed must label its drill-in link 'view all'"
    )


def test_inspector_activity_pulse_class_bound_to_new_flag() -> None:
    """Newly-prepended events must wear `animate-pulse text-accent`
    (Tailwind built-in) for the flash-hold window, then revert to
    `text-foreground-muted`. The :class binding on `_new` is what drives
    that transition — without it nothing distinguishes a fresh event."""
    src = _read("dashboard.html")
    assert "animate-pulse text-accent" in src, (
        "missing pulse styling for newly-arrived activity events"
    )
    assert "ev._new ? 'animate-pulse text-accent' : 'text-foreground-muted'" in src, (
        "activity-feed <li> must toggle pulse class via the ev._new flag"
    )


def test_activity_feed_factory_has_sse_subscription_and_batching() -> None:
    """activityFeed() factory must include:
      - subscribe() that opens an EventSource against /api/network/stream
      - a 1s flush interval that batches buffered events into a single
        DOM update (avoids reflow thrash during call bursts)
      - a 1.5s clear-flash timer that drops the `_new` flag from the
        prepended rows
      - a destroy() that tears down all timers + the EventSource
    These are the contract guarantees the comment in the factory promises;
    locking them here prevents silent regressions when someone removes
    the timers thinking they're dead code."""
    src = _read("dashboard.html")
    # Subscribe + EventSource against the SSE endpoint.
    assert "subscribe()" in src
    assert "new EventSource('/api/network/stream')" in src, (
        "activityFeed must open EventSource against /api/network/stream"
    )
    # Open / error toggles `connected` for the live indicator.
    assert "this.connected = true" in src
    assert "this.connected = false" in src
    # Buffer + 1s flush.
    assert "_buffered" in src
    assert "_flushIntervalMs: 1000" in src
    assert "_flush()" in src
    # 1.5s flash-clear timer.
    assert "_flashHoldMs: 1500" in src
    # Cap at 10 — same number used by the initial load() limit.
    assert "_maxEvents: 10" in src
    # Tear-down.
    assert "destroy()" in src
    assert "this._eventSource.close()" in src


def test_activity_feed_initial_load_endpoint_unchanged() -> None:
    """Initial load + 10s poll fallback must remain — environments that
    proxy-block SSE still need a working feed. Locks the contract from
    test_v19_inspector_content.py so this phase doesn't accidentally
    drop the polling path."""
    src = _read("dashboard.html")
    assert "/api/network/events?limit=10" in src
    assert "this._interval = setInterval(() => this.load(), 10000)" in src


def test_inspector_activity_feed_dedupes_against_existing_events() -> None:
    """The flush path must dedupe newly-arrived events against rows
    already in `events` (same timestamp_ms+tool+target tuple) — without
    it, a brief overlap between the initial /api/network/events fetch
    and the first SSE delivery would render duplicate rows."""
    src = _read("dashboard.html")
    assert "const seen = new Set(drained.map(" in src, (
        "_flush() must build a Set of (timestamp_ms+tool+target) keys"
    )
    assert "this.events.filter(e => !seen.has(" in src, (
        "_flush() must filter existing events through the dedup Set"
    )
