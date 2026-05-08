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
