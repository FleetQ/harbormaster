"""v12.0.0a5: network stats by-source breakdown + worktree helper.

Two small items shipped together.

Endpoint extension (`/api/network/stats`):
  - Existing fields preserved (total_calls, by_tool, top_projects_by_calls,
    error_rate).
  - NEW `by_source` dict: {<source>: {"calls": N, "error_rate": F}}.
    Lets the dashboard distinguish operator-initiated calls from
    project-to-project routing and spot a misbehaving project quickly.

Helper script (`scripts/wt-merge.sh`):
  - --help flag prints usage.
  - Refuses to run from main / master.
  - Auto-detects the parent repo path via `git worktree list`.
  - Documents the workflow invariants in a script header.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log
from harbormaster.ui.network_store import NetworkStore


def setup_function() -> None:
    network_log.clear()


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- by_source breakdown --------------------------------------------


def test_stats_includes_by_source_field() -> None:
    """The stats() return shape gains a `by_source` dict alongside
    the existing fields."""
    store = NetworkStore(db_path=Path("/tmp/_test_by_src.db"))
    store.clear()
    s = store.stats()
    assert "by_source" in s
    assert "total_calls" in s
    assert "by_tool" in s
    assert "top_projects_by_calls" in s
    assert "error_rate" in s


def test_stats_by_source_groups_calls_per_caller(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    for _ in range(3):
        store.record(caller="operator", target="alpha", tool="ask_project")
    for _ in range(2):
        store.record(caller="alpha", target="beta", tool="ask_project")
    store.record(caller="alpha", target="beta", tool="ask_project", status="error")
    s = store.stats()
    by_src = s["by_source"]
    assert isinstance(by_src, dict)
    assert by_src["operator"]["calls"] == 3
    assert by_src["operator"]["error_rate"] == 0.0
    assert by_src["alpha"]["calls"] == 3
    # 1 error of 3 calls = ~0.333
    assert abs(float(by_src["alpha"]["error_rate"]) - (1 / 3)) < 0.01


def test_stats_by_source_with_window_filters_correctly(tmp_path: Path) -> None:
    """The since_ms filter applies to by_source the same way it
    applies to total / by_tool — old rows must not bleed in."""
    import time as time_mod
    store = NetworkStore(db_path=tmp_path / "n.db")
    store.record(caller="operator", target="alpha", tool="ask_project")
    time_mod.sleep(0.05)  # ensure clear ms separation
    cutoff = int(time_mod.time() * 1000)
    time_mod.sleep(0.05)
    store.record(caller="operator", target="alpha", tool="ask_project")
    store.record(caller="operator", target="alpha", tool="ask_project")

    s_recent = store.stats(since_ms=cutoff)
    assert s_recent["by_source"]["operator"]["calls"] == 2
    s_all = store.stats()
    assert s_all["by_source"]["operator"]["calls"] == 3


def test_stats_by_source_empty_db_returns_empty_dict(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    store.clear()
    s = store.stats()
    assert s["by_source"] == {}


def test_stats_endpoint_returns_by_source_field(tmp_path: Path) -> None:
    """API smoke: the `/api/network/stats` endpoint surfaces the new
    field in its JSON response."""
    client = TestClient(create_app(_config(tmp_path)))
    network_log.record(caller="operator", target="x", tool="ask_project")
    r = client.get("/api/network/stats?window=24h")
    assert r.status_code == 200
    body = r.json()
    assert "by_source" in body
    assert body["by_source"]["operator"]["calls"] >= 1


def test_network_panel_renders_by_source(tmp_path: Path) -> None:
    """The HTML page includes a by-source cell + Alpine x-for over
    `stats?.by_source`."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/network").text
    assert "by source" in body
    assert "stats?.by_source ?? {}" in body
    # Per-source error_rate badge is included.
    assert "row.error_rate" in body


# -- worktree helper script ------------------------------------------


SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "wt-merge.sh"
)


def test_wt_merge_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing script: {SCRIPT}"
    # Executable bit set on commit.
    mode = SCRIPT.stat().st_mode
    assert mode & 0o111, f"script not executable (mode {oct(mode)})"


def test_wt_merge_script_help_flag_works() -> None:
    """`--help` prints usage and exits 0 — no git operations needed
    so the test is hermetic."""
    bash = shutil.which("bash")
    assert bash is not None
    proc = subprocess.run(
        [bash, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout
    assert "wt-merge.sh" in proc.stdout


def test_wt_merge_script_documents_invariants() -> None:
    """The script header documents the contract operators rely on:
    enforce clean tree, refuse main, auto-detect parent, --no-ff,
    never force-push."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Working tree" in text
    assert "main" in text and "master" in text
    assert "git worktree list" in text
    assert "--no-ff" in text
    assert "force-push" in text or "force push" in text


def test_wt_merge_script_uses_env_remote_override() -> None:
    """REMOTE env override allows the script to push to a non-default
    remote without code changes — useful for fork-based workflows."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'REMOTE="${REMOTE:-origin}"' in text


def test_wt_merge_script_uses_no_ff_merge_format() -> None:
    """Merge commit message format is `Merge ${BRANCH}` (the v14.0.0a2
    fix braced the variable to avoid the `set -u` ellipsis bug; the
    bare `$BRANCH` form is also accepted for backwards compat)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "git merge --no-ff" in text
    assert ("Merge ${BRANCH}" in text) or ("Merge $BRANCH" in text)


def test_wt_merge_script_uses_set_e_safe_mode() -> None:
    """`set -euo pipefail` is mandatory for any shell script — guards
    against surprise success when a `git push` fails silently in the
    middle of a chain."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
