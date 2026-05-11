"""Tests for the per-project user_hidden state file + endpoints (v21.0.5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.ui.app import create_app
from harbormaster.ui.user_hidden import (
    UserHiddenStore,
    default_state_path,
    reset_default_store_for_tests,
)

# ----- UserHiddenStore unit tests -------------------------------------


def test_store_returns_empty_when_file_missing(tmp_path: Path) -> None:
    store = UserHiddenStore(path=tmp_path / "user_hidden.json")
    assert store.list() == []


def test_add_persists_to_disk(tmp_path: Path) -> None:
    state = tmp_path / "user_hidden.json"
    store = UserHiddenStore(path=state)
    assert store.add("alpha") is True
    assert state.is_file()
    payload = json.loads(state.read_text())
    assert payload == {"names": ["alpha"]}


def test_add_idempotent(tmp_path: Path) -> None:
    store = UserHiddenStore(path=tmp_path / "user_hidden.json")
    assert store.add("alpha") is True
    assert store.add("alpha") is False
    assert store.list() == ["alpha"]


def test_remove_idempotent(tmp_path: Path) -> None:
    store = UserHiddenStore(path=tmp_path / "user_hidden.json")
    store.add("alpha")
    assert store.remove("alpha") is True
    assert store.remove("alpha") is False
    assert store.list() == []


def test_add_rejects_invalid_name(tmp_path: Path) -> None:
    store = UserHiddenStore(path=tmp_path / "user_hidden.json")
    for bad in ["../escape", "name with space", ".hidden", "x/y", ""]:
        with pytest.raises(ValueError, match="invalid project name"):
            store.add(bad)


def test_corrupted_file_returns_empty(tmp_path: Path) -> None:
    state = tmp_path / "user_hidden.json"
    state.write_text("not-json{{{")
    store = UserHiddenStore(path=state)
    assert store.list() == []


def test_malicious_names_in_file_filtered_on_read(tmp_path: Path) -> None:
    """A corrupted state file mustn't be able to smuggle in path traversal."""
    state = tmp_path / "user_hidden.json"
    state.write_text(json.dumps({"names": ["good-name", "../bad", "evil/path"]}))
    store = UserHiddenStore(path=state)
    assert store.list() == ["good-name"]


def test_default_path_honours_env_override(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    target = tmp_path / "custom" / "user_hidden.json"
    monkeypatch.setenv("HARBORMASTER_USER_HIDDEN_FILE", str(target))
    assert default_state_path() == target


# ----- /api/user-hidden endpoint tests --------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Fresh client + isolated state file per test."""
    monkeypatch.setenv(
        "HARBORMASTER_USER_HIDDEN_FILE", str(tmp_path / "user_hidden.json"),
    )
    reset_default_store_for_tests()
    return TestClient(create_app(HarbormasterConfig()))


def test_get_user_hidden_initially_empty(client: TestClient) -> None:
    r = client.get("/api/user-hidden")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "names": []}


def test_post_then_get_user_hidden(client: TestClient) -> None:
    r = client.post("/api/user-hidden", json={"name": "alpha"})
    assert r.status_code == 200
    assert r.json() == {"name": "alpha", "added": True}

    r = client.get("/api/user-hidden")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["names"] == ["alpha"]


def test_post_idempotent(client: TestClient) -> None:
    client.post("/api/user-hidden", json={"name": "alpha"})
    r = client.post("/api/user-hidden", json={"name": "alpha"})
    assert r.status_code == 200
    assert r.json() == {"name": "alpha", "added": False}


def test_post_rejects_invalid_name(client: TestClient) -> None:
    r = client.post("/api/user-hidden", json={"name": "../escape"})
    assert r.status_code == 400


def test_post_rejects_missing_name(client: TestClient) -> None:
    r = client.post("/api/user-hidden", json={})
    assert r.status_code == 422  # pydantic validation


def test_post_rejects_extra_fields(client: TestClient) -> None:
    r = client.post(
        "/api/user-hidden", json={"name": "alpha", "evil": "payload"},
    )
    assert r.status_code == 422  # extra="forbid"


def test_delete_user_hidden(client: TestClient) -> None:
    client.post("/api/user-hidden", json={"name": "alpha"})
    r = client.delete("/api/user-hidden/alpha")
    assert r.status_code == 200
    assert r.json() == {"name": "alpha", "removed": True}
    assert client.get("/api/user-hidden").json()["count"] == 0


def test_delete_idempotent(client: TestClient) -> None:
    r = client.delete("/api/user-hidden/never-added")
    assert r.status_code == 200
    assert r.json() == {"name": "never-added", "removed": False}


def test_delete_rejects_invalid_name(client: TestClient) -> None:
    # `..` doesn't match the project-name regex. Use a single dot which
    # decodes cleanly to one URL path segment so the route DOES match,
    # then the regex guard at handler entry rejects with 400 (vs the
    # routing layer 404-ing on `..%2Fescape` before the handler runs).
    r = client.delete("/api/user-hidden/.hidden")
    assert r.status_code == 400
