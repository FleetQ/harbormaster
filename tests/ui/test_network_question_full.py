"""v21.0.8: the chat tab can lazy-fetch the full request body for a
single mcp_calls row via ``GET /api/network/events/{id}/full``.

These tests pin three guarantees of the v21.0.8 patch:

1. The ``question_full`` column is added by an idempotent migration —
   opening an old database file (one missing the column) succeeds and
   adds the column; opening a fresh database starts with the column;
   opening either one twice is a no-op.

2. ``NetworkStore.record(question_full=...)`` persists the untrimmed
   body alongside the 200-char ``question_preview`` and returns a
   ``NetworkEvent`` carrying the inserted row's ``id``.

3. ``GET /api/network/events/{id}/full`` returns the full body + the
   preview for a known id, and 404s on an unknown id. Rows recorded
   before the migration (``question_full IS NULL``) return
   ``question_full=null`` so the UI falls back to the preview.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.ui.app import create_app
from harbormaster.ui.network_log import network_log
from harbormaster.ui.network_store import NetworkStore

# ---------- schema migration -------------------------------------------------


def test_fresh_store_has_question_full_column(tmp_path: Path) -> None:
    """Opening a brand-new database creates the column up front."""
    store = NetworkStore(db_path=tmp_path / "net.db")
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(mcp_calls)")}
    assert "question_full" in cols
    store.close()


def test_migration_adds_column_to_legacy_db(tmp_path: Path) -> None:
    """Open a database WITHOUT the new column (simulating a pre-v21.0.8
    deployment), then re-open through NetworkStore — the column must
    be added without losing existing rows."""
    db = tmp_path / "legacy.db"
    # Bypass NetworkStore so we set up the v11 schema verbatim — no
    # question_full column.
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE mcp_calls (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp INTEGER NOT NULL,
          source TEXT NOT NULL,
          target TEXT NOT NULL,
          tool TEXT NOT NULL,
          status TEXT NOT NULL,
          duration_ms INTEGER,
          question_preview TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO mcp_calls "
        "(timestamp, source, target, tool, status, duration_ms, question_preview) "
        "VALUES (1, 'operator', 'alpha', 'ask_project', 'ok', 5, 'pre-migration')",
    )
    conn.commit()
    conn.close()

    store = NetworkStore(db_path=db)
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(mcp_calls)")}
    assert "question_full" in cols

    # Legacy row survives and has question_full=NULL.
    events = store.recent()
    assert len(events) == 1
    assert events[0].target == "alpha"
    assert events[0].question_preview == "pre-migration"
    full = store.get_full(events[0].id or -1)
    assert full is not None
    assert full["question_full"] is None
    assert full["question_preview"] == "pre-migration"
    store.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """A second NetworkStore on the same db must not error."""
    db = tmp_path / "net.db"
    store_a = NetworkStore(db_path=db)
    store_a.record(caller="op", target="alpha", tool="ask_project",
                   question_preview="x", question_full="x")
    store_a.close()

    # Re-open. The ALTER TABLE path must short-circuit when the column
    # is already present.
    store_b = NetworkStore(db_path=db)
    cols = {row[1] for row in store_b._conn.execute("PRAGMA table_info(mcp_calls)")}
    assert "question_full" in cols
    assert len(store_b.recent()) == 1
    store_b.close()


# ---------- record / get_full ------------------------------------------------


def test_record_persists_full_text_uncapped(tmp_path: Path) -> None:
    """The 200-char cap must apply ONLY to question_preview; the full
    column receives the untrimmed body."""
    store = NetworkStore(db_path=tmp_path / "net.db")
    long_body = "ABC" * 1000  # 3000 chars

    ev = store.record(
        caller="operator", target="alpha", tool="ask_project",
        question_preview=long_body, question_full=long_body,
    )

    assert len(ev.question_preview) == 200
    assert ev.id is not None
    assert ev.id > 0

    full = store.get_full(ev.id)
    assert full is not None
    assert full["question_full"] == long_body
    assert len(full["question_full"] or "") == 3000
    store.close()


def test_record_without_full_stores_null(tmp_path: Path) -> None:
    """Legacy callers that don't pass ``question_full`` must still
    work; the column is NULL and get_full reflects that."""
    store = NetworkStore(db_path=tmp_path / "net.db")
    ev = store.record(
        caller="operator", target="alpha", tool="ask_project",
        question_preview="hello",
    )

    full = store.get_full(ev.id or -1)
    assert full is not None
    assert full["question_full"] is None
    assert full["question_preview"] == "hello"
    store.close()


def test_recent_includes_row_id(tmp_path: Path) -> None:
    """recent() must populate NetworkEvent.id so SSE pushes + the UI
    list-view know the row's identity for the lazy-fetch."""
    store = NetworkStore(db_path=tmp_path / "net.db")
    store.record(caller="op", target="a", tool="ask_project",
                 question_preview="x", question_full="x")
    store.record(caller="op", target="b", tool="ask_project",
                 question_preview="y", question_full="y")

    events = store.recent()
    assert len(events) == 2
    ids = [e.id for e in events]
    assert all(isinstance(i, int) for i in ids)
    assert ids[0] != ids[1]
    store.close()


def test_get_full_returns_none_for_unknown_id(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "net.db")
    assert store.get_full(999_999) is None
    store.close()


# ---------- API endpoint -----------------------------------------------------


def _seed_event(**kwargs: object) -> int:
    """Insert one row via the session-wide ``network_log`` singleton and
    return its row id."""
    ev = network_log.record(  # type: ignore[arg-type]
        caller=str(kwargs.get("caller", "operator")),
        target=str(kwargs.get("target", "alpha")),
        tool=str(kwargs.get("tool", "ask_project")),
        question_preview=str(kwargs.get("question_preview", "preview")),
        question_full=kwargs.get("question_full"),  # type: ignore[arg-type]
    )
    assert ev.id is not None
    return ev.id


def test_api_full_endpoint_returns_full_body() -> None:
    long_body = "Q" * 5000
    event_id = _seed_event(question_preview=long_body, question_full=long_body)

    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get(f"/api/network/events/{event_id}/full")
    assert r.status_code == 200
    body = r.json()
    assert body["event_id"] == event_id
    assert body["question_full"] == long_body
    # Preview stays capped at 200 chars even when the full body is huge.
    assert len(body["question_preview"]) == 200


def test_api_full_endpoint_404s_on_unknown_id() -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/api/network/events/9999999/full")
    assert r.status_code == 404


def test_api_full_endpoint_returns_null_for_legacy_row() -> None:
    """A row without question_full (pre-v21.0.8) must still return 200,
    with question_full=null so the UI falls back to the preview."""
    event_id = _seed_event(
        question_preview="legacy", question_full=None,
    )

    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get(f"/api/network/events/{event_id}/full")
    assert r.status_code == 200
    body = r.json()
    assert body["question_full"] is None
    assert body["question_preview"] == "legacy"


def test_api_events_list_includes_row_id() -> None:
    """The list endpoint must surface ``id`` so the chat row can call
    ``/api/network/events/{id}/full`` on expand."""
    _seed_event(target="alpha", question_full="hello")

    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/api/network/events?limit=10")
    assert r.status_code == 200
    events = r.json()["events"]
    assert events, "expected at least one event"
    assert all("id" in e and isinstance(e["id"], int) for e in events), events
