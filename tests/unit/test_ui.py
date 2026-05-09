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
