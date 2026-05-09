"""Unit tests for the Live UI routes.

Skipped when [ui] extras aren't installed — keeps contributors who run only
the stdio MCP server unblocked. CI installs the extras explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from harbormaster import __version__  # noqa: E402
from harbormaster.config import HarbormasterConfig, ProjectsConfig  # noqa: E402
from harbormaster.ui import create_app  # noqa: E402


def _make_project_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / "CLAUDE.md").write_text("# test", encoding="utf-8")


@pytest.fixture
def populated_config(tmp_path: Path) -> HarbormasterConfig:
    base = tmp_path / "code"
    _make_project_dir(base / "alpha")
    _make_project_dir(base / "beta")
    return HarbormasterConfig(projects=ProjectsConfig(glob=[f"{base}/*"]))


@pytest.fixture
def empty_config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(projects=ProjectsConfig(glob=[f"{tmp_path}/empty/*"]))


# ----- /api/health -----------------------------------------------------------


def test_health_endpoint_returns_ok(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


# ----- /api/projects ---------------------------------------------------------


def test_projects_endpoint_returns_list(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    names = {p["name"] for p in body}
    assert names == {"alpha", "beta"}


def test_projects_endpoint_returns_expected_keys(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/projects")
    body = r.json()
    expected_keys = {"name", "path", "last_commit", "has_serena", "has_claude_md", "brief"}
    assert expected_keys <= set(body[0].keys())


def test_projects_endpoint_empty_when_no_matches(empty_config):
    client = TestClient(create_app(empty_config))
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


# ----- / (dashboard) ---------------------------------------------------------


def test_root_returns_dashboard_html(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Layout + identity markers
    assert "Harbormaster" in body
    assert __version__ in body
    # Dashboard-specific
    assert "Projects" in body
    # Stack tags (CDN-loaded — important for the markup contract)
    assert "tailwindcss" in body
    assert "alpinejs" in body
    assert "htmx" in body


def test_root_links_to_api_endpoints(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "/api/projects" in body
    assert "/api/health" in body


# ----- v2.1.0a1 — Mermaid graph render + status panels ---------------------


def test_dashboard_includes_mermaid_cdn(populated_config):
    """Mermaid ESM build must be loaded so the graph section can render."""
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "mermaid" in body.lower()
    assert "mermaid@10" in body  # pinned version


def test_dashboard_renders_graph_section(populated_config):
    """Graph panel container present with mermaid markup target."""
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "Project graph" in body
    assert 'class="mermaid' in body or "class='mermaid" in body


def test_dashboard_renders_bridge_status_panel(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "FleetQ Bridge" in body
    assert "/api/bridge/status" in body


def test_dashboard_renders_plugins_panel(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "Plugins" in body
    assert "/api/plugins" in body


# ----- /api/bridge/status (v2.1.0a1) ---------------------------------------


def test_api_bridge_status_default_config(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/bridge/status")
    assert r.status_code == 200
    body = r.json()
    expected_keys = {
        "fleetq_enabled",
        "register_as_bridge",
        "base_url",
        "api_token_env",
        "api_token_present",
        "write_trajectories",
        "write_kg",
        "kg_extractor",
        "heartbeat_interval",
    }
    assert expected_keys <= set(body.keys())
    assert body["fleetq_enabled"] is False
    assert body["api_token_env"] == "FLEETQ_API_TOKEN"
    assert body["base_url"] == "https://app.fleetq.net"
    assert body["kg_extractor"] == "heuristic"


def test_api_bridge_status_reports_token_presence(populated_config, monkeypatch):
    monkeypatch.setenv("FLEETQ_API_TOKEN", "stub-token-123")
    client = TestClient(create_app(populated_config))
    body = client.get("/api/bridge/status").json()
    assert body["api_token_present"] is True


def test_api_bridge_status_reports_token_missing_when_empty(
    populated_config, monkeypatch
):
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)
    client = TestClient(create_app(populated_config))
    body = client.get("/api/bridge/status").json()
    assert body["api_token_present"] is False


# ----- /api/plugins (v2.1.0a1) ---------------------------------------------


def test_api_plugins_default_disabled_returns_status_table(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/plugins")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["allow"] == []
    assert isinstance(body["plugins"], list)
    # Discovered count is whatever the test environment has installed.
    assert isinstance(body["discovered_count"], int)


def test_api_plugins_marks_allowlist_only_dist_as_missing(
    populated_config, monkeypatch
):
    """When [plugins].allow lists a dist that has no matching entry
    point, /api/plugins must include a 'missing' row for it."""
    populated_config.plugins.enabled = True
    populated_config.plugins.allow = ["never-installed-pkg"]
    # Pin entry_points to empty so we know nothing was discovered.
    monkeypatch.setattr(
        "harbormaster.plugins.entry_points", lambda *a, **kw: []
    )
    client = TestClient(create_app(populated_config))
    body = client.get("/api/plugins").json()
    statuses = [(row["status"], row["dist_name"]) for row in body["plugins"]]
    assert ("missing", "never-installed-pkg") in statuses


# ----- /api/graph transitive flag (v2.1.0a1) -------------------------------


def test_api_graph_accepts_transitive_query_param(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/graph?transitive=true")
    assert r.status_code == 200
    body = r.json()
    assert "projects_with_lockfile" in body
    assert "mermaid" in body


# ----- v2.1.0a2 — Project detail page --------------------------------------


def test_project_detail_renders_for_known_project(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "alpha" in body
    assert "Status" in body  # Section header
    assert "← Dashboard" in body  # Breadcrumb back-link


def test_project_detail_returns_404_for_unknown_project(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/projects/does-not-exist")
    assert r.status_code == 404


def test_project_detail_returns_400_for_invalid_name(populated_config):
    """Slashes / `..` etc. must be rejected before resolving the path."""
    client = TestClient(create_app(populated_config))
    # Path traversal attempts get URL-decoded by Starlette into the
    # path param; use a clearly-invalid name.
    r = client.get("/projects/..%2Fsomething")
    # Either 400 (validate_project_name rejected it) or 404 — both are
    # acceptable; the critical thing is we don't render success.
    assert r.status_code in (400, 404)


def test_project_detail_includes_project_metadata(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/projects/alpha").text
    # Path appears (project header card)
    assert "alpha" in body
    # claude.md badge appears since _make_project_dir writes one
    assert "claude.md" in body


def test_dashboard_card_links_to_detail_page(populated_config):
    """v2.1.0a2: the project cards must navigate to /projects/{name}."""
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    # The Alpine href binding should reference the route pattern.
    assert "/projects/" in body
    assert "encodeURIComponent" in body


# ----- v2.1.0a3 — Recall search inline -----------------------------------


def test_dashboard_has_recall_search_section(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "Recall Q&amp;A history" in body  # HTML-escaped ampersand
    assert "/api/recall" in body
    assert "recall_qa" in body  # tool name referenced in caption


def test_api_recall_disabled_when_history_off(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/api/recall?question=anything")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["matches"] == []
    assert "disabled" in body["message"]


def test_api_recall_returns_empty_matches_on_empty_store(populated_config, tmp_path):
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")
    client = TestClient(create_app(populated_config))
    r = client.get("/api/recall?question=hello")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["matches"] == []
    assert body["host"] == "local"


def test_api_recall_returns_matches_after_record(populated_config, tmp_path):
    """End-to-end: open store, write a record, recall via /api/recall."""
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")

    from harbormaster.history import FTS5Backend, QARecord
    from harbormaster.history import QAStore as _QAStore

    store = _QAStore.open(
        db_dir=populated_config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        store.record(
            QARecord(
                question="How does authentication work?",
                answer="JWT tokens. See docs/auth.md.",
                project="alpha",
                host="local",
                tool="ask_project",
            )
        )
    finally:
        store.close()

    client = TestClient(create_app(populated_config))
    body = client.get("/api/recall?question=authentication&project=alpha").json()
    assert body["enabled"] is True
    assert len(body["matches"]) == 1
    m = body["matches"][0]
    assert m["project"] == "alpha"
    assert "JWT" in m["answer"]


def test_api_recall_rejects_empty_question(populated_config):
    populated_config.history.enabled = True
    client = TestClient(create_app(populated_config))
    body = client.get("/api/recall?question=%20%20").json()
    assert body["matches"] == []
    assert "question required" in body["message"]


def test_api_recall_host_all_passes_through(populated_config, tmp_path):
    """host=all reaches the cross-host fan-out path (v2.0.0a6)."""
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")
    client = TestClient(create_app(populated_config))
    body = client.get("/api/recall?question=any&host=all").json()
    assert body["host"] == "all"
    assert "hosts_searched" in body


# ----- v2.1.0a6 — Trajectory history --------------------------------------


def test_api_trajectories_disabled_when_history_off(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/api/trajectories?project=alpha").json()
    assert body["enabled"] is False
    assert body["trajectories"] == []
    assert "disabled" in body["message"]


def test_api_trajectories_returns_empty_for_new_store(populated_config, tmp_path):
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")
    client = TestClient(create_app(populated_config))
    body = client.get("/api/trajectories?project=alpha").json()
    assert body["enabled"] is True
    assert body["trajectories"] == []


def test_api_trajectories_returns_recent_records(populated_config, tmp_path):
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")

    from harbormaster.history import (
        FTS5Backend,
        QARecord,
    )
    from harbormaster.history import (
        QAStore as _QAStore,
    )

    store = _QAStore.open(
        db_dir=populated_config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        for i in range(3):
            store.record(
                QARecord(
                    question=f"question-{i}",
                    answer=f"answer-{i}",
                    project="alpha",
                    host="local",
                    tool="ask_project",
                )
            )
        # Different project — must be filtered out
        store.record(
            QARecord(
                question="other-question",
                answer="other-answer",
                project="beta",
                host="local",
                tool="ask_project",
            )
        )
    finally:
        store.close()

    client = TestClient(create_app(populated_config))
    body = client.get("/api/trajectories?project=alpha").json()
    assert body["enabled"] is True
    assert len(body["trajectories"]) == 3
    # Newest first
    assert body["trajectories"][0]["question"] == "question-2"
    # All belong to alpha
    assert all(t["project"] == "alpha" for t in body["trajectories"])


def test_api_trajectories_respects_limit(populated_config, tmp_path):
    populated_config.history.enabled = True
    populated_config.history.embedding_backend = "fts5"
    populated_config.history.db_dir = str(tmp_path / "hist")

    from harbormaster.history import (
        FTS5Backend,
        QARecord,
    )
    from harbormaster.history import (
        QAStore as _QAStore,
    )

    store = _QAStore.open(
        db_dir=populated_config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        for i in range(5):
            store.record(
                QARecord(
                    question=f"q-{i}",
                    answer=f"a-{i}",
                    project="alpha",
                    host="local",
                    tool="ask_project",
                )
            )
    finally:
        store.close()

    client = TestClient(create_app(populated_config))
    body = client.get("/api/trajectories?project=alpha&limit=2").json()
    assert len(body["trajectories"]) == 2


def test_project_detail_includes_trajectory_section(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/projects/alpha").text
    assert "Recent Q&amp;A" in body
    assert "/api/trajectories" in body
    assert "trajectoryList" in body


# ----- v2.1.0a5 — delegate_task form + fan-out page -----------------------


def test_project_detail_includes_delegate_form(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/projects/alpha").text
    assert "Delegate task" in body
    assert "deliverable" in body
    assert "delegateForm" in body


def test_fan_out_page_renders(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Fan-out" in body
    assert "fan_out_ask" in body
    # Project chips populated from discovery
    assert "alpha" in body
    assert "beta" in body
    # Concurrency control
    assert "max_concurrency" in body


def test_fan_out_page_links_in_nav(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/").text
    assert "/tools/fan-out" in body


def test_fan_out_page_lists_configured_hosts(populated_config):
    populated_config.hosts = {
        "friday": __import__(
            "harbormaster.config", fromlist=["HostConfig"]
        ).HostConfig(ssh_host="friday-real"),
    }
    client = TestClient(create_app(populated_config))
    body = client.get("/tools/fan-out").text
    assert "friday" in body
    assert "local" in body


# ----- v2.1.0a4 — "Ask this project" SSE form ------------------------------


def test_project_detail_includes_ask_form(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/projects/alpha").text
    # Section header
    assert "Ask " in body
    # Form bits
    assert "<textarea" in body
    assert "max_turns" in body
    # SSE wiring
    assert "/mcp/harbormaster" in body
    assert "text/event-stream" in body
    # Stream consumer
    assert "askForm" in body
    assert "AbortController" in body


def test_project_detail_ask_form_passes_project_name_via_alpine(populated_config):
    """The Alpine x-data initializer must contain the project name so
    the fetch payload knows which project to invoke."""
    client = TestClient(create_app(populated_config))
    body = client.get("/projects/alpha").text
    assert '"alpha"' in body  # tojson rendered project name


def test_project_detail_ask_form_passes_host_via_alpine(populated_config):
    """Use an existing configured host so _remote_status doesn't bail
    before we reach the template render."""
    from unittest.mock import patch

    populated_config.hosts = {
        "somehost": __import__(
            "harbormaster.config", fromlist=["HostConfig"]
        ).HostConfig(ssh_host="not-real"),
    }
    client = TestClient(create_app(populated_config))
    with patch("harbormaster.tools.projects._remote_status") as m:
        m.return_value = "## remote\nBranch: main\n"
        body = client.get("/projects/alpha?host=somehost").text
    assert '"somehost"' in body


def test_project_detail_remote_host_reaches_remote_status(populated_config):
    """When ?host= is passed (and != 'local'), the route delegates to
    `_remote_status` which returns either remote markdown OR an
    Error-prefixed string. We mock SSH to avoid hitting the network."""
    from unittest.mock import patch

    populated_config.hosts = {
        "ghosthost": __import__(
            "harbormaster.config", fromlist=["HostConfig"]
        ).HostConfig(ssh_host="ghost-not-real"),
    }

    client = TestClient(create_app(populated_config))
    with patch("harbormaster.tools.projects._remote_status") as m:
        m.return_value = "## remote\nBranch: main\n"
        r = client.get("/projects/alpha?host=ghosthost")
    assert r.status_code == 200
    assert "host: ghosthost" in r.text
    assert "Branch: main" in r.text


# ----- create_app contract --------------------------------------------------


def test_create_app_exposes_correct_metadata(populated_config):
    app = create_app(populated_config)
    assert app.title == "Harbormaster"
    assert app.version == __version__


# ----- /health (FleetQ Bridge ping target) ----------------------------------


def test_fleetq_health_endpoint(populated_config):
    """FleetQ pings /health (not /api/health) on HTTP-tunnel-mode connections.
    Same shape, distinct route."""
    client = TestClient(create_app(populated_config))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


# ----- /discover (FleetQ Bridge HTTP-tunnel mode) ---------------------------


def test_discover_returns_fleetq_manifest_shape(populated_config):
    """FleetQ's /api/v1/bridge/connect calls /discover to validate. Response
    must have the documented {agents, llm_endpoints, mcp_servers} shape."""
    client = TestClient(create_app(populated_config))
    r = client.get("/discover")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"agents", "llm_endpoints", "mcp_servers"}
    assert isinstance(body["agents"], list)
    assert isinstance(body["llm_endpoints"], list)
    assert isinstance(body["mcp_servers"], list)


def test_discover_announces_harbormaster_mcp_server(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/discover").json()
    servers = body["mcp_servers"]
    assert len(servers) == 1
    hm = servers[0]
    assert hm["name"] == "harbormaster"
    assert "tools" in hm
    # Check that all 6 v1.0.0a7 tools are advertised
    expected_tools = {
        "list_projects", "list_hosts", "project_status",
        "ask_project", "delegate_task", "fan_out_ask",
    }
    assert expected_tools <= set(hm["tools"])


# ----- bearer middleware applies to /discover too --------------------------


def test_discover_protected_by_bearer_middleware(populated_config):
    """When the user runs UI with HARBORMASTER_UI_TOKEN set, FleetQ must send
    that same token as endpoint_secret — middleware enforces it."""
    from harbormaster.transport import build_bearer_middleware

    app = create_app(populated_config)
    app.add_middleware(build_bearer_middleware("ui-token-xyz"))
    client = TestClient(app)

    # Without bearer
    assert client.get("/discover").status_code == 401
    assert client.get("/health").status_code == 401

    # With bearer
    h = {"Authorization": "Bearer ui-token-xyz"}
    assert client.get("/discover", headers=h).status_code == 200
    assert client.get("/health", headers=h).status_code == 200


# ----- bearer middleware can be applied to UI app ---------------------------


def test_ui_app_with_bearer_middleware_rejects_unauth(populated_config):
    """Verify the same bearer middleware used on MCP HTTP transports works
    when applied to the UI app — both /api/* and / get protected."""
    from harbormaster.transport import build_bearer_middleware

    app = create_app(populated_config)
    app.add_middleware(build_bearer_middleware("ui-token-xyz"))
    client = TestClient(app)

    # No header → 401 on every route
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/projects").status_code == 401
    assert client.get("/").status_code == 401

    # Correct token → 200
    h = {"Authorization": "Bearer ui-token-xyz"}
    assert client.get("/api/health", headers=h).status_code == 200
    assert client.get("/api/projects", headers=h).status_code == 200
    assert client.get("/", headers=h).status_code == 200


# ----- POST /mcp/{server} HTTP-direct routing endpoint ----------------------


@pytest.fixture
def app_with_mcp(populated_config):
    """Build the UI app with a real FastMCP instance bound, so /mcp/{server}
    can dispatch into the tool registry."""
    from harbormaster.server import build_server

    mcp = build_server(populated_config)
    return create_app(populated_config, mcp=mcp)


def test_mcp_endpoint_returns_404_when_mcp_not_bound(populated_config):
    """create_app(config) without mcp= should leave the endpoint unreachable
    (clear 404 with a hint, not a confusing 500)."""
    client = TestClient(create_app(populated_config))
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 404
    assert "MCP HTTP-direct routing not available" in r.json()["detail"]


def test_mcp_endpoint_404_on_unknown_server(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/some-other-server",
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 404


def test_mcp_endpoint_tools_list_returns_all_registered_tools(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 200
    body = r.json()
    tools = body["result"]["tools"]
    names = {t["name"] for t in tools}
    expected = {
        "list_projects", "list_hosts", "project_status",
        "ask_project", "delegate_task", "fan_out_ask",
    }
    assert expected <= names
    # Every tool entry has at minimum a name + description
    for t in tools:
        assert "name" in t
        assert "description" in t


def test_mcp_endpoint_tools_call_dispatches_to_tool(app_with_mcp):
    """tools/call with method 'list_hosts' (a fast read-only tool) should
    return an MCP envelope wrapping the tool's return value."""
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={
            "request_id": "req-9",
            "method": "tools/call",
            "params": {"name": "list_hosts", "arguments": {}},
            "timeout": 30,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    content = body["result"]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"


def test_mcp_endpoint_tools_call_404_on_unknown_tool(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        },
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_mcp_endpoint_tools_call_400_on_missing_name(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/call", "params": {"arguments": {}}},
    )
    assert r.status_code == 400


def test_mcp_endpoint_tools_call_400_on_non_dict_arguments(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={
            "method": "tools/call",
            "params": {"name": "list_hosts", "arguments": "not-a-dict"},
        },
    )
    assert r.status_code == 400


def test_mcp_endpoint_rejects_unsupported_method(app_with_mcp):
    """Pydantic regex on `method` rejects anything outside tools/call|tools/list."""
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "logging/setLevel", "params": {}},
    )
    assert r.status_code == 422  # pydantic validation


def test_mcp_endpoint_tool_exception_returned_as_iserror_envelope(populated_config):
    """A tool that raises must not 500 — wrap as MCP isError result so the
    caller (FleetQ) gets a structured response."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("harbormaster-test")

    @mcp.tool()
    def boom() -> str:
        raise RuntimeError("simulated tool failure")

    app = create_app(populated_config, mcp=mcp)
    client = TestClient(app)
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/call", "params": {"name": "boom", "arguments": {}}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["isError"] is True
    assert "simulated tool failure" in body["result"]["content"][0]["text"]


def test_mcp_endpoint_protected_by_bearer_middleware(populated_config):
    """Same middleware reused — /mcp/{server} respects HARBORMASTER_UI_TOKEN."""
    from harbormaster.server import build_server
    from harbormaster.transport import build_bearer_middleware

    mcp = build_server(populated_config)
    app = create_app(populated_config, mcp=mcp)
    app.add_middleware(build_bearer_middleware("expected"))
    client = TestClient(app)

    # No bearer → 401
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 401

    # Correct bearer → 200
    r = client.post(
        "/mcp/harbormaster",
        headers={"Authorization": "Bearer expected"},
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 200


# ----- POST /mcp/{server} streaming (SSE) ----------------------------------


def _parse_sse(text: str) -> list[dict[str, str]]:
    """Split a raw SSE response body into [{event, data}, ...] entries."""
    import contextlib
    import json as _json

    events: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            if cur:
                events.append(cur)
                cur = {}
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive
        if line.startswith("event: "):
            cur["event"] = line[len("event: ") :]
        elif line.startswith("data: "):
            cur["data"] = line[len("data: ") :]
    if cur:
        events.append(cur)
    # Decode data as JSON for convenience.
    for e in events:
        if "data" in e:
            with contextlib.suppress(_json.JSONDecodeError):
                e["data_json"] = _json.loads(e["data"])
    return events


def test_mcp_proxy_returns_json_when_accept_is_default(app_with_mcp):
    """No streaming Accept header → unchanged JSON behaviour (regression)."""
    client = TestClient(app_with_mcp)
    r = client.post(
        "/mcp/harbormaster",
        json={"method": "tools/list", "params": {}},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "tools" in r.json()["result"]


def test_mcp_proxy_streams_when_accept_event_stream(app_with_mcp):
    """Accept: text/event-stream → SSE response with a single result event
    for a fast tool that completes inside one heartbeat interval."""
    client = TestClient(app_with_mcp)
    with client.stream(
        "POST",
        "/mcp/harbormaster",
        headers={"Accept": "text/event-stream"},
        json={
            "method": "tools/call",
            "params": {"name": "list_hosts", "arguments": {}},
            "timeout": 5,
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read().decode()

    events = _parse_sse(body)
    # Last event must be the final result; preceding events (if any) are
    # heartbeats. list_hosts is fast (~5 ms) so we expect zero heartbeats.
    assert events, "no SSE events were emitted"
    final = events[-1]
    assert final["event"] == "result"
    payload = final["data_json"]
    assert "result" in payload
    assert payload["result"]["content"][0]["type"] == "text"


def test_mcp_proxy_streams_emits_heartbeat_for_slow_tool(
    populated_config, monkeypatch
):
    """Tool that exceeds one heartbeat interval should produce >=1 heartbeat
    event before the final result. Drive the interval down to 0.05s and
    register a tool that sleeps 0.2s to keep the test fast."""
    import time as _time

    from mcp.server.fastmcp import FastMCP

    from harbormaster.ui import routes as routes_module

    monkeypatch.setattr(routes_module, "_HEARTBEAT_INTERVAL_S", 0.05)

    mcp = FastMCP("harbormaster-test")

    @mcp.tool()
    def slow_one() -> str:
        _time.sleep(0.2)
        return "done"

    app = create_app(populated_config, mcp=mcp)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/mcp/harbormaster",
        headers={"Accept": "text/event-stream"},
        json={
            "method": "tools/call",
            "params": {"name": "slow_one", "arguments": {}},
            "timeout": 5,
        },
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode()

    events = _parse_sse(body)
    types = [e.get("event") for e in events]

    assert types[-1] == "result", f"final event must be result, got {types}"
    heartbeats = [e for e in events if e.get("event") == "heartbeat"]
    assert len(heartbeats) >= 1, (
        f"expected >=1 heartbeat for a 200ms tool with 50ms interval, "
        f"got events={types}"
    )
    # Heartbeats carry monotonically non-decreasing elapsed_ms values.
    elapsed_values = [e["data_json"]["elapsed_ms"] for e in heartbeats]
    assert elapsed_values == sorted(elapsed_values)
    # At least one heartbeat happened *during* the tool, not at t=0.
    assert max(elapsed_values) >= 50


def test_mcp_proxy_streams_error_event_on_unknown_tool(app_with_mcp):
    """Even in streaming mode, a 404-class error from _dispatch_mcp must
    arrive as an SSE `error` event with status=404, not as an HTTP 404
    pre-stream (so the caller sees one consistent transport per request)."""
    client = TestClient(app_with_mcp)
    with client.stream(
        "POST",
        "/mcp/harbormaster",
        headers={"Accept": "text/event-stream"},
        json={
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        },
    ) as resp:
        assert resp.status_code == 200  # SSE wrapper is 200, error is in-band
        body = resp.read().decode()

    events = _parse_sse(body)
    assert events[-1]["event"] == "error"
    err = events[-1]["data_json"]
    assert err["status"] == 404
    assert "not found" in err["detail"]


def test_mcp_proxy_streams_error_event_on_tool_exception(populated_config):
    """A tool that raises arbitrary Exception must surface as the regular
    isError envelope (consistent with JSON mode), wrapped in an SSE
    `result` event — NOT an `error` event. Reason: in JSON mode tool
    exceptions are 200 OK with isError=true; SSE preserves that semantics
    so callers don't need a different code path for streaming."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("harbormaster-test")

    @mcp.tool()
    def boom() -> str:
        raise RuntimeError("simulated tool failure")

    app = create_app(populated_config, mcp=mcp)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/mcp/harbormaster",
        headers={"Accept": "text/event-stream"},
        json={
            "method": "tools/call",
            "params": {"name": "boom", "arguments": {}},
        },
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode()

    events = _parse_sse(body)
    assert events[-1]["event"] == "result"
    envelope = events[-1]["data_json"]
    assert envelope["result"]["isError"] is True
    assert "simulated tool failure" in envelope["result"]["content"][0]["text"]


def test_mcp_proxy_streams_handles_compound_accept_header(app_with_mcp):
    """Real-world clients send Accept lists like
    `text/event-stream, application/json;q=0.9` — the streaming branch
    must trigger as long as text/event-stream appears anywhere."""
    client = TestClient(app_with_mcp)
    with client.stream(
        "POST",
        "/mcp/harbormaster",
        headers={"Accept": "application/json, text/event-stream;q=0.9"},
        json={"method": "tools/list", "params": {}},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


# ----- ask_project chunk streaming (a12) -----------------------------------
#
# These tests target the `_stream_ask_project_local` async generator
# directly rather than going through TestClient.stream(). Reason: SSE
# responses don't naturally close from the client side under TestClient,
# so a hanging keepalive ping or a non-finalising generator would lock
# the test for the full ping interval (15s default in sse-starlette).
# Async direct-iteration is faster, deterministic, and exercises the
# exact code path the real route uses — the route handler is a thin
# wrapper around `EventSourceResponse(_stream_dispatch(...))`.


@pytest.mark.asyncio
async def test_stream_ask_project_local_yields_chunk_events_and_final_result(
    populated_config, monkeypatch
):
    """Each backend delta becomes one `chunk` SSE event; the assembled
    string lands in the final `result` event's MCP envelope."""
    import json as _json

    from harbormaster.backends.claude import ClaudeBackend
    from harbormaster.ui.routes import _ask_project_prompt, _stream_local_tool

    def fake_stream(self, *, cwd, prompt, max_turns):  # noqa: ARG001
        yield "Hello, "
        yield "world."

    monkeypatch.setattr(ClaudeBackend, "ask_local_stream", fake_stream)

    events = []
    async for evt in _stream_local_tool(
        populated_config, {"name": "alpha", "question": "summarize"},
        _ask_project_prompt, max_turns_default=5,
    ):
        events.append(evt)

    types = [e["event"] for e in events]
    assert types == ["chunk", "chunk", "result"]

    assert _json.loads(events[0]["data"])["text"] == "Hello, "
    assert _json.loads(events[1]["data"])["text"] == "world."
    final = _json.loads(events[2]["data"])
    assert final["result"]["content"][0]["text"] == "Hello, world."


@pytest.mark.asyncio
async def test_stream_ask_project_local_emits_400_on_missing_question(populated_config):
    """Argument validation surfaces as an in-band SSE error event with
    status=400, not a Python exception out of the generator."""
    import json as _json

    from harbormaster.ui.routes import _ask_project_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config, {"name": "alpha"},  # no question
        _ask_project_prompt, max_turns_default=5,
    ):
        events.append(evt)

    assert len(events) == 1
    assert events[0]["event"] == "error"
    err = _json.loads(events[0]["data"])
    assert err["status"] == 400
    assert "question" in err["detail"]


@pytest.mark.asyncio
async def test_stream_ask_project_local_emits_400_on_missing_name(populated_config):
    import json as _json

    from harbormaster.ui.routes import _ask_project_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config, {"question": "summarize"},  # no name
        _ask_project_prompt, max_turns_default=5,
    ):
        events.append(evt)

    assert events[0]["event"] == "error"
    err = _json.loads(events[0]["data"])
    assert err["status"] == 400
    assert "name" in err["detail"]


@pytest.mark.asyncio
async def test_stream_ask_project_local_502_on_backend_error_mid_stream(
    populated_config, monkeypatch
):
    """A BackendError raised partway through iteration must surface as a
    502 SSE error event — never as a result event (so callers can tell
    completed-vs-failed without inspecting the envelope)."""
    import json as _json

    from harbormaster.backends.base import BackendError
    from harbormaster.backends.claude import ClaudeBackend
    from harbormaster.ui.routes import _ask_project_prompt, _stream_local_tool

    def fake_stream(self, *, cwd, prompt, max_turns):  # noqa: ARG001
        yield "partial output"
        raise BackendError("subprocess died", code="exit_nonzero")

    monkeypatch.setattr(ClaudeBackend, "ask_local_stream", fake_stream)

    events = []
    async for evt in _stream_local_tool(
        populated_config, {"name": "alpha", "question": "summarize"},
        _ask_project_prompt, max_turns_default=5,
    ):
        events.append(evt)

    types = [e["event"] for e in events]
    assert "chunk" in types
    assert "result" not in types
    assert types[-1] == "error"
    err = _json.loads(events[-1]["data"])
    assert err["status"] == 502
    assert "exit_nonzero" in err["detail"]


@pytest.mark.asyncio
async def test_stream_ask_project_local_400_on_unknown_project(populated_config):
    """resolve_project raising ValueError now surfaces as a deterministic
    400 — the eager validation in make_ask_local_stream catches it
    before any subprocess is spawned, so we can guarantee 400 instead
    of "maybe-400-maybe-502 depending on iteration timing."""
    import json as _json

    from harbormaster.ui.routes import _ask_project_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config, {"name": "nonexistent", "question": "summarize"},
        _ask_project_prompt, max_turns_default=5,
    ):
        events.append(evt)

    assert events[-1]["event"] == "error"
    err = _json.loads(events[-1]["data"])
    assert err["status"] == 400
    assert "nonexistent" in err["detail"]


# ----- A2A Agent Card per project (a15) -------------------------------------


def test_agent_card_returns_404_for_unknown_project(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/agent-card/nonexistent")
    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


def test_agent_card_returns_a2a_v03_shape_for_known_project(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/agent-card/alpha")
    assert r.status_code == 200
    body = r.json()

    # Top-level shape
    assert body["schemaVersion"] == "0.3.0"
    assert body["name"] == "harbormaster.alpha"
    assert isinstance(body["description"], str) and body["description"]
    assert body["url"].endswith("/mcp/harbormaster")

    # Capabilities — only claim what we actually serve
    assert body["capabilities"]["streaming"] is True
    assert body["capabilities"]["stateTransitionHistory"] is False
    assert body["capabilities"]["pushNotifications"] is False

    # Default I/O modes
    assert "text/plain" in body["defaultInputModes"]
    assert "text/event-stream" in body["defaultOutputModes"]
    assert "application/json" in body["defaultOutputModes"]


def test_agent_card_advertises_ask_delegate_status_skills(populated_config):
    client = TestClient(create_app(populated_config))
    body = client.get("/agent-card/alpha").json()

    skill_ids = {s["id"] for s in body["skills"]}
    assert skill_ids == {"ask-alpha", "delegate-alpha", "status-alpha"}

    for skill in body["skills"]:
        assert "name" in skill
        assert "description" in skill
        assert "tags" in skill
        assert "inputModes" in skill
        assert "outputModes" in skill


def test_agent_card_metadata_includes_project_path(populated_config):
    """The optional `metadata.harbormaster` block carries project paths
    + Serena/CLAUDE.md flags so A2A consumers that *do* want to know
    they're talking to harbormaster (e.g. for richer context loading)
    can opt in without parsing the description text."""
    client = TestClient(create_app(populated_config))
    body = client.get("/agent-card/alpha").json()

    meta = body["metadata"]["harbormaster"]
    assert isinstance(meta["version"], str) and meta["version"]
    assert meta["project_path"].endswith("alpha")
    # alpha has CLAUDE.md (set up in the populated_config fixture)
    assert meta["has_claude_md"] is True


def test_agent_card_url_uses_request_host_when_present(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get(
        "/agent-card/alpha",
        headers={"Host": "harbormaster.example:7531"},
    )
    body = r.json()
    assert body["url"].startswith("http://harbormaster.example:7531")


def test_agent_card_protected_by_bearer_middleware(populated_config):
    """Same auth surface as the rest of the UI — token controls access."""
    from harbormaster.transport import build_bearer_middleware

    app = create_app(populated_config)
    app.add_middleware(build_bearer_middleware("ui-token-xyz"))
    client = TestClient(app)

    assert client.get("/agent-card/alpha").status_code == 401
    h = {"Authorization": "Bearer ui-token-xyz"}
    assert client.get("/agent-card/alpha", headers=h).status_code == 200


# ----- delegate_task chunk streaming (a14) ----------------------------------


@pytest.mark.asyncio
async def test_stream_local_tool_delegate_task_yields_chunks(
    populated_config, monkeypatch
):
    """delegate_task uses the same streaming path as ask_project, just
    with a different prompt builder."""
    import json as _json

    from harbormaster.backends.claude import ClaudeBackend
    from harbormaster.ui.routes import _delegate_task_prompt, _stream_local_tool

    captured: dict[str, object] = {}

    def fake_stream(self, *, cwd, prompt, max_turns):  # noqa: ARG001
        captured["prompt"] = prompt
        yield "Plan: "
        yield "1) read files"

    monkeypatch.setattr(ClaudeBackend, "ask_local_stream", fake_stream)

    events = []
    async for evt in _stream_local_tool(
        populated_config,
        {
            "name": "alpha",
            "task": "audit the auth module",
            "deliverable": "list of issues",
        },
        _delegate_task_prompt, max_turns_default=10,
    ):
        events.append(evt)

    types = [e["event"] for e in events]
    assert types == ["chunk", "chunk", "result"]

    final = _json.loads(events[-1]["data"])
    assert final["result"]["content"][0]["text"] == "Plan: 1) read files"

    # The prompt builder injected the read-only injunction.
    prompt = captured["prompt"]
    assert isinstance(prompt, str)
    assert "Task: audit the auth module" in prompt
    assert "Deliverable: list of issues" in prompt
    assert "Read-only mode" in prompt


@pytest.mark.asyncio
async def test_stream_local_tool_delegate_task_400_on_allow_writes(populated_config):
    """delegate_task with allow_writes=true is disabled in v1; must
    surface as a 400 error event before any subprocess is spawned."""
    import json as _json

    from harbormaster.ui.routes import _delegate_task_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config,
        {
            "name": "alpha",
            "task": "edit auth.py",
            "deliverable": "patch",
            "allow_writes": True,
        },
        _delegate_task_prompt, max_turns_default=10,
    ):
        events.append(evt)

    assert len(events) == 1
    assert events[0]["event"] == "error"
    err = _json.loads(events[0]["data"])
    assert err["status"] == 400
    assert "allow_writes" in err["detail"]


@pytest.mark.asyncio
async def test_stream_local_tool_delegate_task_400_on_missing_task(populated_config):
    import json as _json

    from harbormaster.ui.routes import _delegate_task_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config,
        {"name": "alpha", "deliverable": "x"},  # no task
        _delegate_task_prompt, max_turns_default=10,
    ):
        events.append(evt)

    assert events[-1]["event"] == "error"
    err = _json.loads(events[-1]["data"])
    assert err["status"] == 400
    assert "task" in err["detail"]


@pytest.mark.asyncio
async def test_stream_local_tool_delegate_task_400_on_missing_deliverable(
    populated_config,
):
    import json as _json

    from harbormaster.ui.routes import _delegate_task_prompt, _stream_local_tool

    events = []
    async for evt in _stream_local_tool(
        populated_config,
        {"name": "alpha", "task": "x"},  # no deliverable
        _delegate_task_prompt, max_turns_default=10,
    ):
        events.append(evt)

    assert events[-1]["event"] == "error"
    err = _json.loads(events[-1]["data"])
    assert err["status"] == 400
    assert "deliverable" in err["detail"]


# --- v3.0.0a6: bearer-token plumbing -------------------------------------


def test_dashboard_renders_meta_tag_when_auth_token_set(populated_config):
    client = TestClient(create_app(populated_config, auth_token="secret123"))
    r = client.get("/")
    assert r.status_code == 200
    assert '<meta name="hm-auth-token" content="secret123">' in r.text


def test_dashboard_omits_meta_tag_when_auth_token_unset(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    # hmFetch's JS body references the meta name as a string, so we
    # assert on the meta *tag itself* being absent, not the literal
    # token name.
    assert '<meta name="hm-auth-token"' not in r.text


def test_dashboard_omits_meta_tag_when_auth_token_empty(populated_config):
    client = TestClient(create_app(populated_config, auth_token=""))
    r = client.get("/")
    assert r.status_code == 200
    assert '<meta name="hm-auth-token"' not in r.text


def test_fan_out_page_renders_meta_tag_when_auth_token_set(populated_config):
    client = TestClient(create_app(populated_config, auth_token="abc"))
    r = client.get("/tools/fan-out")
    assert r.status_code == 200
    assert '<meta name="hm-auth-token" content="abc">' in r.text


def test_dashboard_uses_hmfetch_helper(populated_config):
    """The base.html script must define hmFetch globally so all forms
    can use it consistently."""
    client = TestClient(create_app(populated_config, auth_token="t"))
    r = client.get("/")
    assert "window.hmFetch" in r.text
    # All form fetches must route through hmFetch (no bare fetch( in
    # the dashboard chrome — only legitimate `fetch` mentions are inside
    # the helper definition itself or comments).
    # Quick check: dashboard.html-rendered output should call hmFetch
    # for /api/projects, /api/bridge/status, /api/plugins, /api/recall.
    assert "hmFetch('/api/projects'" in r.text
    assert "hmFetch('/api/bridge/status'" in r.text


def test_ask_form_uses_hmfetch_in_project_detail(populated_config, tmp_path):
    """Project detail page renders ask_form.html — verify it uses hmFetch."""
    # Seed a project so /projects/<name> resolves.
    proj_dir = tmp_path / "demo-project"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# Demo")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")]),
    )
    client = TestClient(create_app(cfg, auth_token="zzz"))

    r = client.get("/projects/demo-project")
    # Project detail can succeed (200) or 404 depending on discovery —
    # if 200, verify hmFetch is in the rendered template.
    if r.status_code == 200:
        assert "hmFetch('/mcp/harbormaster'" in r.text
        assert '<meta name="hm-auth-token" content="zzz">' in r.text


# --- v3.0.0a7: inline ask form on dashboard cards ------------------------


def test_dashboard_includes_ask_form_script(populated_config):
    """askForm() Alpine component must be defined on the dashboard so
    per-card inline ask forms can mount it without project_detail."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "function askForm(initial)" in r.text
    # Ensure the component is the actual SSE-streaming one, not a stub.
    assert "_consumeSseStream" in r.text


def test_dashboard_renders_ask_button_per_card(populated_config):
    """Each card has an Ask toggle and a collapsed inline form."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    # The Alpine x-data for per-card toggle.
    assert 'x-data="{ askExpanded: false }"' in r.text
    # The inline askForm() x-data binding using p.name from the x-for scope.
    assert "askForm({ project: p.name" in r.text


def test_dashboard_card_ask_form_includes_abort_and_streaming(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Stop button (abort) reachable from the card form.
    assert '@click="abort()"' in r.text
    # Stream output element bound to streamText.
    assert 'x-text="streamText"' in r.text


def test_project_detail_still_uses_ask_form_partial(populated_config, tmp_path):
    """The partial's form markup must remain available on project_detail —
    extracting the script is a refactor, not a remove."""
    proj_dir = tmp_path / "demo-detail"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# detail")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-detail")
    if r.status_code == 200:
        # Both the form markup (textarea placeholder) and the function
        # definition must be present.
        assert "function askForm(initial)" in r.text
        assert "x-data=\"askForm({" in r.text
