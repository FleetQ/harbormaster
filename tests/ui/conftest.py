"""Shared fixtures for browser-driven UI tests (v3.0.0a10).

Opt-in via `pytest -m browser`. Skipped by default so the regular
test suite doesn't need Playwright + chromium installed.

The `ui_url` fixture spins up `harbormaster-ui` in a subprocess on
loopback (no auth), polls /api/health for readiness, then yields the
base URL. The subprocess is terminated in fixture teardown.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest


def _free_port() -> int:
    """Bind a socket to port 0 to ask the OS for a free port, then close."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def ui_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Boot `harbormaster-ui` on a random loopback port; yield URL."""
    pytest.importorskip(
        "playwright",
        reason="ui-test extra not installed; install with `uv sync --extra ui-test`",
    )
    import httpx

    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    # Use a tmp config file so per-session test runs don't leak state.
    cfg_dir = tmp_path_factory.mktemp("ui-config")
    cfg = cfg_dir / "config.toml"
    cfg.write_text(
        f"[projects]\nglob = ['{cfg_dir}/projects/*']\n\n"
        "[server]\nui_port = "
        f"{port}\n",
    )
    (cfg_dir / "projects").mkdir()
    # Seed one project so /api/projects has at least one element to render.
    (cfg_dir / "projects" / "demo-browser").mkdir()
    (cfg_dir / "projects" / "demo-browser" / "README.md").write_text("# demo")
    # v19 sidebar groups projects by detected language. A bare project
    # with only README.md gets no language → may not render in any group
    # by default. Seed a minimal pyproject.toml so language=python is
    # detected and the project surfaces under the PYTHON group.
    (cfg_dir / "projects" / "demo-browser" / "pyproject.toml").write_text(
        '[project]\nname = "demo-browser"\nversion = "0.0.1"\n'
    )

    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "harbormaster.ui.cli",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--config", str(cfg),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Poll /api/health up to 10s.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                r = httpx.get(f"{url}/api/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"harbormaster-ui did not become healthy within 10s\n"
                f"stdout: {stdout.decode()[:2000]}\n"
                f"stderr: {stderr.decode()[:2000]}"
            )
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
