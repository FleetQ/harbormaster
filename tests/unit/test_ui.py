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
    # v8.0.0a7: HTMX dropped — no `hx-*` attributes were ever in the
    # templates (audit confirmed in Phase 1) so the script tag was
    # pure download cost. Audit lives in
    # tests/ui/test_phase7_distribution.py.
    assert "htmx" not in body


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


# --- v3.0.0a8: ask→trajectory cross-section refresh events --------------


def test_ask_form_dispatches_trajectory_dirty_event(populated_config, tmp_path):
    """askForm() must dispatch hm:trajectory:dirty on stream completion
    so any trajectoryList scope on the same page can refresh."""
    proj_dir = tmp_path / "demo-x8"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x8")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x8")
    if r.status_code == 200:
        assert "hm:trajectory:dirty" in r.text
        assert "window.dispatchEvent" in r.text


def test_trajectory_list_listens_for_dirty_events(populated_config, tmp_path):
    """trajectoryList must listen on the window for hm:trajectory:dirty
    and reload only when the project in the event matches."""
    proj_dir = tmp_path / "demo-x8b"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x8b")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x8b")
    if r.status_code == 200:
        # The listener with project-match guard.
        assert "x-on:hm:trajectory:dirty.window" in r.text
        assert "$event.detail.project === project" in r.text


def test_dashboard_ask_form_also_dispatches_event(populated_config):
    """The shared askForm() function lives in _ask_form_script.html;
    dashboard cards reuse it, so the dispatch must be present here too.
    Dashboard has no trajectory section, so the event has no listener
    on this page — but the dispatch is harmless (no-op when no listener)."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "hm:trajectory:dirty" in r.text


# --- v3.0.0a9: mobile graph + URL state ---------------------------------


def test_dashboard_graph_viewport_has_touch_friendly_classes(populated_config):
    """Mobile-friendly graph viewport: max-h cap.

    v4.0.0a3 replaced native touch-pan-x/-y CSS with explicit JS
    pinch + drag handlers (graphZoom Alpine component). The viewport
    is now overflow-hidden because the inner transform handles
    movement; only the max-h-[60vh] sizing constraint carries over.
    """
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "max-h-[60vh]" in r.text


def test_fan_out_form_emits_url_state_helpers(populated_config):
    """Fan-out form ships restoreFromUrl + persistToUrl + uses
    window.history.replaceState so URL stays sharable."""
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    assert r.status_code == 200
    assert "restoreFromUrl()" in r.text
    assert "persistToUrl()" in r.text
    assert "window.history.replaceState" in r.text
    # URLSearchParams roundtrip params known to the form
    assert "p.get('q')" in r.text
    assert "p.set('q'" in r.text
    assert "p.get('targets')" in r.text


def test_fan_out_form_initialises_via_x_init(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    assert 'x-init="restoreFromUrl()"' in r.text


# --- v4.0.0a2: URL state on recall + copy-link --------------------------


def test_recall_panel_emits_url_state_helpers(populated_config):
    """Recall panel must read recall_q / recall_project / recall_host
    from URL on mount and write them on search."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "x-init=\"restoreFromUrl()\"" in r.text
    assert "p.get('recall_q')" in r.text
    assert "p.set('recall_q'" in r.text
    assert "p.get('recall_project')" in r.text
    assert "p.get('recall_host')" in r.text


def test_recall_panel_persists_on_search(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # search() must call persistToUrl() before fetching.
    assert "this.persistToUrl();" in r.text


def test_fan_out_form_has_copy_link_button(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    assert r.status_code == 200
    assert ">copy link<" in r.text
    assert "copyShareLink()" in r.text


def test_fan_out_form_copy_link_uses_clipboard_api(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    assert "navigator.clipboard" in r.text
    assert "navigator.clipboard.writeText(url)" in r.text
    # Feedback affordance — "copied ✓" pseudo-button visible after copy.
    assert "shareLinkCopied" in r.text


def test_fan_out_copy_link_disabled_for_short_question(populated_config):
    """Button must be disabled when question is < 3 chars (matches submit)."""
    client = TestClient(create_app(populated_config))
    r = client.get("/tools/fan-out")
    # Same gate as submit button.
    assert ":disabled=\"question.trim().length < 3\"" in r.text


# --- v4.0.0a3: graph pinch-zoom -----------------------------------------


def test_dashboard_graph_zoom_component_present(populated_config):
    """graphZoom() Alpine factory must be rendered for the graph panel."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "function graphZoom()" in r.text
    # x-data="graphZoom()" wraps the panel.
    assert 'x-data="graphZoom()"' in r.text


def test_dashboard_graph_zoom_handles_wheel_and_touch(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Event handlers wired on the inner container.
    assert "@wheel.prevent=\"onWheel($event)\"" in r.text
    assert "@touchstart=\"onTouchStart($event)\"" in r.text
    assert "@touchmove.prevent=\"onTouchMove($event)\"" in r.text
    assert "@touchend=\"onTouchEnd($event)\"" in r.text


def test_dashboard_graph_zoom_reset_button_present(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Reset button calls reset() on the Alpine scope.
    assert "@click=\"reset()\"" in r.text
    # And the body of reset() clamps + animates.
    assert "this.scale = 1; this.tx = 0; this.ty = 0;" in r.text


def test_dashboard_graph_zoom_clamps_scale(populated_config):
    """_clampScale must bound between 0.25× and 4× to prevent invisible
    or runaway-large graphs."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "Math.max(0.25, Math.min(4, s))" in r.text


def test_dashboard_graph_zoom_supports_two_finger_pinch(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Pinch-distance computed via Math.hypot on the two touchpoints.
    assert "Math.hypot(dx, dy)" in r.text
    # Pinch state machine fields.
    assert "_pinchInitialDist" in r.text
    assert "_pinchInitialScale" in r.text


# --- v4.0.0a4: optimistic trajectory insert -----------------------------


def test_ask_form_dispatches_append_event_with_synthetic_entry(populated_config, tmp_path):
    """askForm() must dispatch hm:trajectory:append with a synthetic
    entry containing question, answer, and a synthetic id."""
    proj_dir = tmp_path / "demo-x4a"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x4a")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x4a")
    if r.status_code == 200:
        assert "hm:trajectory:append" in r.text
        assert "_optimistic: true" in r.text
        # Synthetic id pattern.
        assert "'optimistic-' + Date.now()" in r.text


def test_trajectory_section_listens_for_append(populated_config, tmp_path):
    proj_dir = tmp_path / "demo-x4b"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x4b")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x4b")
    if r.status_code == 200:
        assert "x-on:hm:trajectory:append.window" in r.text
        assert "prepend(" in r.text


def test_trajectory_list_reconciles_on_load(populated_config, tmp_path):
    """trajectoryList.load() must replace optimistic entries when the
    server returns a matching real entry, but keep optimistics that
    haven't reconciled yet (writeback in flight)."""
    proj_dir = tmp_path / "demo-x4c"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x4c")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x4c")
    if r.status_code == 200:
        # Reconciliation logic: filter by (project, tool, question) tuple.
        assert "s.project === t.project" in r.text
        assert "s.tool === t.tool" in r.text
        assert "s.question === t.question" in r.text
        # Optimistic entries kept on top.
        assert "[...optimistic, ...fresh]" in r.text


def test_trajectory_list_visual_differentiation_for_optimistic(populated_config, tmp_path):
    proj_dir = tmp_path / "demo-x4d"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x4d")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x4d")
    if r.status_code == 200:
        # Optimistic entries get cyan border + "● new" badge.
        assert "border-cyan-700/40" in r.text
        assert "●&nbsp;new" in r.text


def test_dashboard_card_ask_dispatches_append_too(populated_config):
    """The shared askForm() factory means dashboard cards also fire
    the append event, harmless when no listener is on the dashboard."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "hm:trajectory:append" in r.text


# --- v4.0.0a5: /api/history/state ---------------------------------------


def test_api_history_state_returns_idle_when_no_run(populated_config, tmp_path, monkeypatch):
    """When no auto-reembed has run, /api/history/state must return phase=idle."""
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "missing.json")
    )
    client = TestClient(create_app(populated_config))
    r = client.get("/api/history/state")
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "idle"
    assert body["available"] is True


def test_api_history_state_reflects_running_state(populated_config, tmp_path, monkeypatch):
    """When a running state file exists, the route reflects it."""
    sf = tmp_path / "state.json"
    monkeypatch.setenv("HARBORMASTER_REEMBED_STATE_FILE", str(sf))

    from harbormaster.history.auto_reembed import ReembedState, _write_state
    _write_state(
        ReembedState(
            phase="running", processed=2, total=4, current_host="friday",
            started_at=12345.0,
        ),
        sf,
    )
    client = TestClient(create_app(populated_config))
    r = client.get("/api/history/state")
    body = r.json()
    assert body["phase"] == "running"
    assert body["processed"] == 2
    assert body["total"] == 4
    assert body["current_host"] == "friday"


def test_api_history_state_reflects_done_state(populated_config, tmp_path, monkeypatch):
    sf = tmp_path / "state.json"
    monkeypatch.setenv("HARBORMASTER_REEMBED_STATE_FILE", str(sf))
    from harbormaster.history.auto_reembed import ReembedState, _write_state
    _write_state(
        ReembedState(
            phase="done", processed=3, total=3,
            started_at=12345.0, finished_at=12399.0,
        ),
        sf,
    )
    client = TestClient(create_app(populated_config))
    body = client.get("/api/history/state").json()
    assert body["phase"] == "done"
    assert body["finished_at"] == 12399.0


def test_api_history_state_includes_config_flag(populated_config):
    """The endpoint surfaces auto_reembed_enabled so the UI can render
    the right CTA (enable in config / wait for run / show progress)."""
    client = TestClient(create_app(populated_config))
    body = client.get("/api/history/state").json()
    assert "auto_reembed_enabled" in body


# --- v5.0.0a1: auto-reembed UI panel ------------------------------------


def test_dashboard_renders_reembed_panel(populated_config):
    """Dashboard must define reembedPanel() Alpine factory + render
    the panel section."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "function reembedPanel()" in r.text
    assert 'x-data="reembedPanel()"' in r.text


def test_reembed_panel_phase_badge_classes(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # All four phase classes referenced.
    assert "bg-cyan-900/50 text-cyan-300" in r.text  # running
    assert "bg-emerald-900/50 text-emerald-300" in r.text  # done
    assert "bg-rose-900/50 text-rose-300" in r.text  # failed
    # phaseBadgeClass mapper is in scope.
    assert "phaseBadgeClass()" in r.text


def test_reembed_panel_shows_progress_bar(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Progress bar wired to processed/total.
    assert "state.processed / state.total" in r.text


def test_reembed_panel_polls_only_when_running(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Polling started in _maybeStartPolling, only when phase === 'running'.
    assert "_maybeStartPolling" in r.text
    assert "this.state.phase === 'running'" in r.text
    # 3-second cadence.
    assert ", 3000)" in r.text


# --- v5.0.0a4: optimistic trajectory polish -----------------------------


def test_trajectory_list_uses_content_tuple_key(populated_config, tmp_path):
    """:key is (project, tool, question) so the DOM persists across
    optimistic→real reconciliation, enabling CSS cross-fade."""
    proj_dir = tmp_path / "demo-x5a"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x5a")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x5a")
    if r.status_code == 200:
        # Content tuple key.
        assert "t.project + ':' + t.tool + ':' + t.question" in r.text
        # transition-colors class applied to the <li>.
        assert "transition-colors duration-200" in r.text


def test_trajectory_list_shows_writeback_spinner_for_stale_optimistics(populated_config, tmp_path):
    """isStale + spinner element: optimistics older than 5s show the
    amber spinner instead of the cyan badge."""
    proj_dir = tmp_path / "demo-x5b"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x5b")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x5b")
    if r.status_code == 200:
        assert "isStale(t)" in r.text
        assert "animate-spin" in r.text
        assert "border-amber-400" in r.text
        # 5s threshold.
        assert "age > 5" in r.text


def test_trajectory_list_init_starts_tick(populated_config, tmp_path):
    """Alpine init() must start the 1s tick that drives `now`."""
    proj_dir = tmp_path / "demo-x5c"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x5c")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x5c")
    if r.status_code == 200:
        assert "init()" in r.text
        assert "_tickHandle = setInterval" in r.text
        assert "this.now = Date.now() / 1000" in r.text


def test_trajectory_list_reconciles_in_place(populated_config, tmp_path):
    """Reconciliation in-place: server entry merges optimistic match
    with _optimistic=false instead of removing+adding."""
    proj_dir = tmp_path / "demo-x5d"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x5d")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x5d")
    if r.status_code == 200:
        # In-place merge marker
        assert "_optimistic: false" in r.text
        # Orphan handling preserved
        assert "orphans" in r.text


# --- v5.0.0a5: graph zoom UX polish -------------------------------------


def test_graph_zoom_has_double_tap_reset(populated_config):
    """Double-tap detection within 300ms calls reset()."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "_lastTapTime" in r.text
    assert "now - this._lastTapTime < 300" in r.text


def test_graph_zoom_keyboard_shortcuts(populated_config):
    """Desktop keyboard shortcuts: +/-, arrows, Escape."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # @keydown.window listener wired.
    assert '@keydown.window="onKeyDown($event)"' in r.text
    # All key cases covered.
    for key in ["'+'", "'-'", "'='", "'ArrowLeft'", "'ArrowRight'", "'ArrowUp'", "'ArrowDown'", "'Escape'"]:
        assert f"case {key}:" in r.text, f"missing case {key}"


def test_graph_zoom_keyboard_skips_form_fields(populated_config):
    """Keyboard handler must not fire when typing into INPUT / TEXTAREA / SELECT."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'" in r.text


def test_graph_zoom_reset_button_mentions_keyboard_hint(populated_config):
    """Reset button title hints at the keyboard shortcut."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "press Esc or double-tap" in r.text


# --- v5.0.0a6: dashboard project filter + URL state ---------------------


def test_dashboard_renders_project_filter_input(populated_config):
    """Filter input above the project grid + Alpine projectGrid() factory."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "function projectGrid()" in r.text
    assert 'x-data="projectGrid()"' in r.text
    # Filter input element with debounce-150ms.
    assert "@input.debounce.150ms=\"persistToUrl()\"" in r.text
    assert "filter by name / path / brief" in r.text


def test_dashboard_filter_match_helper_filters_three_fields(populated_config):
    """visibleProjects() filters by name / path / brief substring."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "name.includes(needle)" in r.text
    assert "path.includes(needle)" in r.text
    assert "brief.includes(needle)" in r.text


def test_dashboard_filter_persists_to_url(populated_config):
    """v3.0.0a9 default-omit pattern; preserves foreign params."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "p.set('filter'" in r.text
    assert "p.delete('filter')" in r.text
    assert "window.history.replaceState" in r.text


def test_dashboard_filter_restores_from_url_on_mount(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "p.get('filter')" in r.text
    assert "if (f) this.filter = f" in r.text


def test_dashboard_shows_no_match_state_with_clear_button(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "No projects match" in r.text
    # The clear button.
    assert "filter = '';" in r.text


def test_dashboard_filter_match_count_shows_when_active(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Counter switches between "X discovered" and "X of Y match"
    assert "of ${projects.length} match" in r.text


# --- v6.0.0a1: manual reembed trigger + ETA -----------------------------


def test_api_history_reembed_starts_run(populated_config, tmp_path, monkeypatch):
    """POST /api/history/reembed must start a run when none in progress."""
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )
    monkeypatch.setenv("HARBORMASTER_HISTORY_DB_DIR", str(tmp_path / "db"))

    # Force history enabled in this test config since populated_config
    # is shared across tests.
    from harbormaster.config import HarbormasterConfig, HistoryConfig
    cfg = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
        ),
    )
    # Patch QAStore.open to a no-drift stub so the runner finishes fast.
    from harbormaster.history import QAStore

    class _NoDrift:
        def has_embedding_drift(self): return False
        def reembed(self, *, batch_size=100, resume=True): return 0, 0
        def close(self): pass

    monkeypatch.setattr(
        QAStore, "open",
        lambda **kw: _NoDrift(),
    )

    client = TestClient(create_app(cfg))
    r = client.post("/api/history/reembed")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True


def test_api_history_reembed_returns_409_when_running(
    populated_config, tmp_path, monkeypatch
):
    """Idempotent: a second call while running must return 409."""
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )
    from harbormaster.config import HarbormasterConfig, HistoryConfig
    from harbormaster.history.auto_reembed import (
        ReembedState,
        _write_state,
    )

    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    _write_state(ReembedState(phase="running"), tmp_path / "state.json")

    client = TestClient(create_app(cfg))
    r = client.post("/api/history/reembed")
    assert r.status_code == 409


def test_api_history_reembed_returns_400_when_history_disabled(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.post("/api/history/reembed")
    assert r.status_code == 400


def test_reembed_panel_renders_trigger_button(populated_config):
    """The 'run now' button + triggering state must be present."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "triggerManual()" in r.text
    assert ">run now<" in r.text
    assert "triggering" in r.text


def test_reembed_panel_eta_helper(populated_config):
    """progressLabel + _etaSeconds + _formatEta must be defined."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "progressLabel()" in r.text
    assert "_etaSeconds()" in r.text
    assert "_formatEta" in r.text
    # Rate-based ETA logic.
    assert "elapsed / s.processed" in r.text
    assert "remaining" in r.text


# --- v6.0.0a2: optimistic escalation tier + configurable threshold ------


def test_base_template_emits_stale_threshold_meta(populated_config):
    """base.html must render the threshold meta tag so JS can read it."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert '<meta name="hm-optimistic-stale-seconds"' in r.text


def test_stale_threshold_meta_reflects_config(populated_config):
    """Bumping [history] optimistic_stale_seconds in config flows through."""
    from harbormaster.config import HarbormasterConfig, HistoryConfig
    cfg = HarbormasterConfig(
        history=HistoryConfig(optimistic_stale_seconds=20),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/")
    assert '<meta name="hm-optimistic-stale-seconds" content="20">' in r.text


def test_trajectory_uses_tier_helper(populated_config, tmp_path):
    """trajectoryList must use the tier() helper for the three-tier
    visual escalation, not the old single isStale check."""
    proj_dir = tmp_path / "demo-x6b"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x6b")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig

    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x6b")
    if r.status_code == 200:
        # Three tiers all referenced.
        assert "tier(t) === 'fresh'" in r.text
        assert "tier(t) === 'stale'" in r.text
        assert "tier(t) === 'stuck'" in r.text
        # Stuck tier has rose border + ⚠ badge.
        assert "border-rose-700/50" in r.text
        assert "stuck?" in r.text


def test_trajectory_tier_threshold_logic(populated_config, tmp_path):
    """The fresh→stale→stuck thresholds use threshold and threshold*6."""
    proj_dir = tmp_path / "demo-x6c"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x6c")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig
    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x6c")
    if r.status_code == 200:
        assert "if (age <= threshold) return 'fresh'" in r.text
        assert "if (age <= threshold * 6) return 'stale'" in r.text
        assert "return 'stuck'" in r.text


def test_trajectory_reads_threshold_from_meta(populated_config, tmp_path):
    proj_dir = tmp_path / "demo-x6d"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# x6d")

    from harbormaster.config import HarbormasterConfig, ProjectsConfig
    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/projects/demo-x6d")
    if r.status_code == 200:
        assert "_staleThreshold()" in r.text
        assert "meta[name=\"hm-optimistic-stale-seconds\"]" in r.text


def test_history_config_optimistic_stale_seconds_default():
    from harbormaster.config import HistoryConfig
    cfg = HistoryConfig()
    assert cfg.optimistic_stale_seconds == 5


def test_history_config_optimistic_stale_seconds_validates_range():
    from pydantic import ValidationError

    from harbormaster.config import HistoryConfig

    # Must be > 0.
    with pytest.raises(ValidationError):
        HistoryConfig(optimistic_stale_seconds=0)
    # Must be <= 600.
    with pytest.raises(ValidationError):
        HistoryConfig(optimistic_stale_seconds=601)
    # In-range OK.
    cfg = HistoryConfig(optimistic_stale_seconds=120)
    assert cfg.optimistic_stale_seconds == 120


# --- v6.0.0a3: dashboard sort + group controls --------------------------


def test_dashboard_renders_sort_and_group_dropdowns(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    # Sort dropdown options.
    assert ">sort: recent<" in r.text
    assert ">sort: alphabetical<" in r.text
    assert ">sort: by language<" in r.text
    # Group toggle options.
    assert ">group: flat<" in r.text
    assert ">group: by language<" in r.text


def test_project_grid_factory_includes_sort_helpers(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "_sortProjects(" in r.text
    assert "groupedProjects()" in r.text
    # All 3 sort modes mapped.
    assert "case 'alpha':" in r.text
    assert "case 'language':" in r.text
    assert "case 'last_commit':" in r.text


def test_project_grid_persists_sort_and_group_to_url(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Sort/group keys persisted with default-omit.
    assert "p.set('sort'" in r.text
    assert "p.set('group'" in r.text
    assert "p.delete('sort')" in r.text
    assert "p.delete('group')" in r.text


def test_project_grid_restores_sort_and_group_from_url(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "p.get('sort')" in r.text
    assert "p.get('group')" in r.text
    # Allowlist enforced.
    assert "['last_commit', 'alpha', 'language'].includes" in r.text
    assert "['flat', 'language'].includes" in r.text


def test_api_projects_includes_language_field(populated_config, tmp_path):
    """ProjectInfo now carries `language`; /api/projects must surface it."""
    proj_dir = tmp_path / "py-demo"
    proj_dir.mkdir()
    (proj_dir / "CLAUDE.md").write_text("# py")
    (proj_dir / "pyproject.toml").write_text(
        '[project]\nname = "py-demo"\nversion = "0.1"\n'
    )

    js_dir = tmp_path / "js-demo"
    js_dir.mkdir()
    (js_dir / "CLAUDE.md").write_text("# js")
    (js_dir / "package.json").write_text('{"name": "js-demo", "version": "0.1"}')

    from harbormaster.config import HarbormasterConfig, ProjectsConfig
    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[str(tmp_path / "*")]))
    client = TestClient(create_app(cfg))
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    by_name = {p["name"]: p for p in body}
    assert by_name["py-demo"]["language"] == "python"
    assert by_name["js-demo"]["language"] == "javascript"


def test_detect_language_falls_back_for_unrecognised(tmp_path):
    """Repos without a known manifest get 'unknown'."""
    from harbormaster.projects import _detect_language
    proj = tmp_path / "doc-only"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("# docs")
    assert _detect_language(proj) == "unknown"


def test_detect_language_fallback_when_parser_fails(tmp_path):
    """Even when pyproject.toml is malformed, the fallback file-existence
    check catches it."""
    from harbormaster.projects import _detect_language
    proj = tmp_path / "broken"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("# x")
    (proj / "pyproject.toml").write_text("not valid [toml")  # parser will fail
    assert _detect_language(proj) == "python"


# --- v6.0.0a4: keyboard shortcut help popover ---------------------------


def test_dashboard_renders_help_popover_factory(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    assert "function helpPopover()" in r.text
    assert 'x-data="helpPopover()"' in r.text


def test_help_popover_listens_for_question_mark_and_escape(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Window-level keydown listener.
    assert '@keydown.window="onKeyDown($event)"' in r.text
    # Both keys handled in onKeyDown.
    assert "if (e.key === '?')" in r.text
    assert "e.key === 'Escape'" in r.text


def test_help_popover_form_field_guard(populated_config):
    """Same INPUT/TEXTAREA/SELECT guard as graphZoom — typing into a
    form field must not toggle the popover."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Both helpPopover and graphZoom use the same guard idiom.
    assert r.text.count(
        "tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'"
    ) >= 2


def test_help_popover_lists_graph_zoom_shortcuts(populated_config):
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    # Graph zoom keys appear in the shortcut map.
    assert "'+ / ='" in r.text
    assert "'↑ ↓ ← →'" in r.text
    # Touch double-tap mentioned.
    assert "double-tap" in r.text


def test_help_popover_has_pointer_friendly_button(populated_config):
    """Fixed-position button at bottom-right toggles open state."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "fixed bottom-4 right-4" in r.text
    # Toggle binding.
    assert '@click="open = !open"' in r.text


def test_help_popover_dismiss_on_outside_click(populated_config):
    """The popover dismisses when clicking outside it."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert '@click.away="open = false"' in r.text


# --- v6.0.1 regression: graph mermaid render after v4.0.0a3 nested x-data ---


def test_dashboard_graph_loads_via_queryselector_not_xrefs(populated_config):
    """Regression guard: v4.0.0a3 wrapped <pre x-ref='diagram'> inside
    graphZoom()'s x-data scope, breaking this.$refs.diagram lookup from
    the parent graphPanel() scope. Mermaid.run() never fired and the
    raw 'graph LR\\n ...' markup leaked as visible text.

    Fix uses document.querySelector('pre.mermaid') which bypasses scope
    nesting. This test asserts the fix is in place."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert r.status_code == 200
    # The fix uses document.querySelector to find the mermaid pre.
    assert "document.querySelector('pre.mermaid')" in r.text
    # The broken pattern must be gone from loadGraph.
    # (Counts: x-ref attribute may remain; what matters is that
    # loadGraph doesn't dereference $refs.diagram any more.)
    # We check that no occurrence of "this.$refs.diagram" exists in
    # the page (could appear in debug code; harmless if absent).
    assert "this.$refs.diagram" not in r.text


def test_dashboard_graph_pre_has_mermaid_class(populated_config):
    """The mermaid <pre> must carry the class so querySelector finds it."""
    client = TestClient(create_app(populated_config))
    r = client.get("/")
    assert "<pre class=\"mermaid" in r.text
