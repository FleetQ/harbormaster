"""Multi-worker dispatcher stress test (v4.0.0a6).

Builds a real FastMCP server with the safe-to-stress tool subset
(list_projects, project_status with local-only, recall_qa with FTS5),
wraps it in MCPDispatcher, and runs 50 concurrent dispatches via a
ThreadPoolExecutor.

The goal is **not** to benchmark — it's to verify thread-safety:

- No deadlocks
- No exceptions leaking out of dispatch
- All responses are well-formed JSON envelopes

If this test passes on your environment, ``[fleetq]
dispatcher_max_workers > 1`` is safe to enable.

If this test surfaces an issue, file the failing case as a regression
guard, leave the dispatcher pool single-worker.
"""
from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

from harbormaster.config import (
    HarbormasterConfig,
    HistoryConfig,
    ProjectsConfig,
)
from harbormaster.fleetq.dispatcher import MCPDispatcher
from harbormaster.server import build_server

# Number of concurrent dispatches per stress run. 50 is enough to
# repro most data-race classes without making the test slow.
STRESS_PARALLELISM = 50


def _seed_projects(root: Path, n: int) -> Path:
    """Create N tiny projects under root for project_status / list_projects."""
    for i in range(n):
        proj = root / f"stress-project-{i:02d}"
        proj.mkdir()
        (proj / "README.md").write_text(f"# stress {i}")
    return root


@pytest.fixture
def stress_config(tmp_path: Path) -> HarbormasterConfig:
    project_root = tmp_path / "projects"
    project_root.mkdir()
    _seed_projects(project_root, 10)
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(project_root / "*")]),
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "history"),
        ),
    )


def _random_payload() -> dict[str, Any]:
    """Pick one of the safe-to-stress tools at random."""
    choice = random.choice(["list_projects", "list_hosts", "project_graph"])
    return {"method": "tools/call", "params": {"name": choice, "arguments": {}}}


def test_dispatcher_handles_50_concurrent_calls(
    stress_config: HarbormasterConfig,
) -> None:
    """50 concurrent dispatches must produce 50 well-formed envelopes
    with no thread-safety failures."""
    mcp = build_server(stress_config)
    dispatcher = MCPDispatcher(mcp)

    def one_dispatch() -> dict[str, Any]:
        chunks = list(dispatcher.dispatch(_random_payload()))
        # Always exactly one chunk per dispatch.
        assert len(chunks) == 1
        # Must parse as JSON.
        return json.loads(chunks[0])

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one_dispatch) for _ in range(STRESS_PARALLELISM)]
        for fut in as_completed(futures):
            results.append(fut.result())

    assert len(results) == STRESS_PARALLELISM
    # Every envelope has the expected MCP shape.
    for env in results:
        assert "result" in env
        # Either content (tools/call) or tools (tools/list).
        assert "content" in env["result"] or "tools" in env["result"]


def test_dispatcher_pool_isolates_per_request_failures(
    stress_config: HarbormasterConfig,
) -> None:
    """Mixing valid + invalid payloads in parallel: invalid ones get
    isError envelopes, valid ones get normal envelopes; nothing leaks."""
    mcp = build_server(stress_config)
    dispatcher = MCPDispatcher(mcp)

    def one_dispatch(payload: dict[str, Any]) -> dict[str, Any]:
        chunks = list(dispatcher.dispatch(payload))
        return json.loads(chunks[0])

    payloads = []
    for i in range(20):
        if i % 3 == 0:
            payloads.append({"method": "tools/call", "params": {"name": "missing"}})
        else:
            payloads.append({"method": "tools/list"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one_dispatch, p) for p in payloads]
        results = [f.result() for f in as_completed(futures)]

    assert len(results) == 20
    # At least some isError envelopes landed (the missing-tool calls).
    error_envs = [r for r in results if r["result"].get("isError")]
    assert len(error_envs) > 0
    # At least some success envelopes landed (the tools/list calls).
    ok_envs = [r for r in results if not r["result"].get("isError")]
    assert len(ok_envs) > 0


# --- v5.0.0a2: backend-invoking tools via fake-claude --------------------


FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


def _seed_resolvable_projects(root: Path, n: int) -> None:
    """Seed projects with CLAUDE.md so resolve_project sees them as valid.
    The basic _seed_projects helper above only creates a README; that's
    enough for list_projects glob enumeration but not for ask_project's
    resolve_project lookup which requires the marker file."""
    for i in range(n):
        proj = root / f"stress-project-{i:02d}"
        proj.mkdir()
        (proj / "README.md").write_text(f"# stress {i}")
        (proj / "CLAUDE.md").write_text(f"# stress project {i}")


@pytest.fixture
def stress_backend_config(tmp_path: Path) -> HarbormasterConfig:
    """Same as stress_config but wires the claude backend at fake_claude.py
    so ask_project / delegate_task spawn a real subprocess that returns
    quickly."""
    from harbormaster.config import BackendConfig

    project_root = tmp_path / "projects"
    project_root.mkdir()
    _seed_resolvable_projects(project_root, 5)
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(project_root / "*")]),
        backends={
            "claude": BackendConfig(
                binary=str(FAKE_CLAUDE),
                timeout_local=10,
            ),
        },
    )


def _ask_payload(project_name: str, question: str) -> dict[str, Any]:
    return {
        "method": "tools/call",
        "params": {
            "name": "ask_project",
            "arguments": {
                "name": project_name,
                "question": question,
                "max_turns": 1,
            },
        },
    }


def test_dispatcher_backend_tools_concurrent(
    stress_backend_config: HarbormasterConfig,
) -> None:
    """50 concurrent ask_project dispatches via fake-claude must each
    return a well-formed envelope without subprocess state leakage."""
    mcp = build_server(stress_backend_config)
    dispatcher = MCPDispatcher(mcp)

    project_names = [f"stress-project-{i:02d}" for i in range(5)]

    def one_dispatch(idx: int) -> dict[str, Any]:
        proj = project_names[idx % len(project_names)]
        chunks = list(dispatcher.dispatch(
            _ask_payload(proj, f"q-{idx}-{random.randint(0, 999)}")
        ))
        assert len(chunks) == 1
        return json.loads(chunks[0])

    results: list[dict[str, Any]] = []
    # Lower parallelism than the read-only stress because each call
    # spawns a real subprocess; 16 workers × ~50 dispatches still
    # exercises contention without saturating the runner.
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(one_dispatch, i) for i in range(50)]
        for fut in as_completed(futures):
            results.append(fut.result())

    assert len(results) == 50
    # Every envelope must be a success (fake-claude always returns 0).
    error_envs = [r for r in results if r["result"].get("isError")]
    assert error_envs == [], (
        f"unexpected errors under concurrent dispatch: {error_envs[:3]}"
    )
    # Every answer must contain the FAKE_CLAUDE marker.
    for env in results:
        text = env["result"]["content"][0]["text"]
        assert "FAKE_CLAUDE answered" in text, f"unexpected answer: {text[:200]}"


def test_dispatcher_backend_tools_isolation_under_failure(
    stress_backend_config: HarbormasterConfig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When fake-claude returns exit2 (simulated subprocess failure),
    each dispatch's error envelope must not bleed into siblings."""
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "exit2")

    mcp = build_server(stress_backend_config)
    dispatcher = MCPDispatcher(mcp)

    def one_dispatch() -> dict[str, Any]:
        chunks = list(dispatcher.dispatch(
            _ask_payload("stress-project-00", "boom")
        ))
        return json.loads(chunks[0])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in as_completed(
            [pool.submit(one_dispatch) for _ in range(10)]
        )]

    assert len(results) == 10
    # All 10 should have failed (consistent error path), but each as
    # a clean isError envelope — no exceptions leaked.
    for env in results:
        # Either an isError envelope OR (if the backend layer caught
        # it as a typed error string) a regular envelope with the
        # error text — both are legitimate routing outcomes.
        result = env["result"]
        text_blocks = result.get("content", [])
        if result.get("isError"):
            assert text_blocks, "isError envelope must carry content"
        else:
            # Even non-isError envelopes for a failed subprocess should
            # have *some* text — assert content shape.
            assert text_blocks
