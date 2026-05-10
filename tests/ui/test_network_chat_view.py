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
    # The row is collapsible: a button with x-data {open:false} and
    # an inner div bound to ev.question_preview.
    assert "{ open: false }" in src
    assert "ev.question_preview" in src


def test_view_toggle_persists_to_localstorage() -> None:
    src = _read_template()
    # localStorage key contract.
    assert "'hm:network:view'" in src
    # Both setItem and getItem are wired.
    assert "localStorage.setItem('hm:network:view'" in src
    assert "localStorage.getItem('hm:network:view')" in src


def test_view_toggle_skeleton_dispatches_event() -> None:
    src = _read_template()
    assert "$dispatch('hm:network:view', 'graph')" in src
    assert "$dispatch('hm:network:view', 'chat')" in src


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
