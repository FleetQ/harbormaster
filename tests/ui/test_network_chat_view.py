"""v10.0.0a8: chat view + view-toggle on the /network page.

Pins the markup contract for the chat-view alternate that renders
the same MCPCallLog ring buffer as a chronological event log.
View preference persists in localStorage between page loads.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.ui import create_app


def _read_template() -> str:
    return (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "network.html"
    ).read_text()


def test_template_includes_chat_view_block() -> None:
    src = _read_template()
    assert 'id="hm-network-chat"' in src
    assert "view === 'chat'" in src
    assert "chatOrder()" in src


def test_chat_rows_show_caller_arrow_target_format() -> None:
    """Sanity: the chat row template renders the caller, tool,
    target trio so the format `caller → tool(target)` is preserved."""
    src = _read_template()
    # Caller, tool, target tokens all appear in the row template.
    assert 'x-text="ev.caller"' in src
    assert 'x-text="ev.tool"' in src
    assert 'x-text="ev.target"' in src


def test_chat_rows_expand_to_full_preview_on_click() -> None:
    src = _read_template()
    # The row is collapsible: a button toggles `open` and shows
    # ev.question_preview (preview fallback when the v21.0.8
    # full-fetch hasn't completed yet).
    assert "open: false" in src
    assert "ev.question_preview" in src


def test_chat_rows_lazy_fetch_full_request_on_expand() -> None:
    """v21.0.8: clicking a row to expand triggers an HTTP fetch to
    /api/network/events/{id}/full and replaces the preview text with
    the untrimmed body. Rows that lack an id (legacy SSE pushes) or
    rows where the server has no full body cached fall back to the
    preview."""
    src = _read_template()
    assert "loadFull()" in src
    assert "/api/network/events/' + ev.id + '/full" in src
    # Loading + error + fallback states all present.
    assert "loading full request" in src
    assert "failed to load" in src
    # Fallback hint for rows recorded before v21.0.8.
    assert "full body not stored for this older event" in src


def test_view_toggle_persists_to_localstorage() -> None:
    src = _read_template()
    # localStorage key contract.
    assert "'hm:network:view'" in src
    # Both setItem and getItem are wired.
    assert "localStorage.setItem('hm:network:view'" in src
    assert "localStorage.getItem('hm:network:view')" in src


def test_view_toggle_skeleton_dispatches_event() -> None:
    """v21.0.0a6: the inline view-switch buttons were replaced by a
    shared tab strip (`_partials/_tabs.html`). networkTabs.setTab()
    now centralises the `hm:network:view` dispatch so the existing
    networkPanel() listener keeps working unchanged."""
    src = _read_template()
    assert "hm:network:view" in src
    assert "new CustomEvent('hm:network:view'" in src
    # Tabs include both graph and chat ids — these are the values
    # that get passed through as `detail` on the dispatch.
    assert "id: 'graph'" in src
    assert "id: 'chat'" in src


def test_chat_order_is_newest_first() -> None:
    """`chatOrder()` returns events in reverse so the latest call
    is at the top — matches operator expectations for an event log."""
    src = _read_template()
    assert "chatOrder()" in src
    assert "...this.events].reverse()" in src


def test_network_html_still_renders() -> None:
    """End-to-end smoke: /network still serves and contains the new
    chat scaffold."""
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/network")
    assert r.status_code == 200
    body = r.text
    assert "hm-network-graph" in body
    assert "hm-network-chat" in body
