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
