"""v15.0.0a2 — concurrent multi-host plugin discovery + cross-host config diff."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HostConfig
from harbormaster.plugins import query_remote_config
from harbormaster.ui import create_app

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _fake_completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ssh", "fake"], returncode=returncode,
        stdout=stdout, stderr=stderr,
    )


# -- query_remote_config -------------------------------------------


def test_query_remote_config_returns_remote_text() -> None:
    host = HostConfig(ssh_host="alpha.local")
    text = "[server]\nname = 'alpha'\n"
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=text),
    ):
        r = query_remote_config(host)
    assert r["text"] == text
    assert r["path"] == "~/.config/harbormaster.toml"
    assert "error" not in r


def test_query_remote_config_handles_ssh_layer_failure() -> None:
    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=255,
            stderr="ssh: connect to host alpha.local port 22: Connection refused",
        ),
    ):
        r = query_remote_config(host)
    assert r["text"] == ""
    assert "Connection refused" in r["error"]


def test_query_remote_config_handles_remote_nonzero_exit() -> None:
    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=1, stderr="cat: ~/.config/harbormaster.toml: No such file",
        ),
    ):
        r = query_remote_config(host)
    assert r["text"] == ""
    assert "No such file" in r["error"]


def test_query_remote_config_handles_ssh_timeout() -> None:
    from harbormaster.ssh import SshTimeoutError

    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        side_effect=SshTimeoutError("SSH to 'alpha.local' exceeded 120s"),
    ):
        r = query_remote_config(host)
    assert r["text"] == ""
    assert "exceeded" in r["error"]


# -- /api/plugins?host=all (concurrent fan-out) --------------------


def test_api_plugins_host_all_returns_envelope_with_local() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/plugins?host=all")
        assert r.status_code == 200
        body = r.json()
        assert "hosts" in body
        # No remote hosts configured — only "local" key.
        assert "local" in body["hosts"]
        assert "discovered_count" in body["hosts"]["local"]


def test_api_plugins_host_all_concurrent_fanout() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(ssh_host="alpha.local"),
            "beta": HostConfig(ssh_host="beta.local"),
        },
    )
    app = create_app(cfg)
    fake_payload: dict[str, Any] = {
        "enabled": True, "allow": [], "discovered_count": 0,
        "plugins": [],
    }
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=json.dumps(fake_payload)),
    ), TestClient(app) as client:
        r = client.get("/api/plugins?host=all")
        assert r.status_code == 200
        body = r.json()
        assert set(body["hosts"].keys()) == {"local", "alpha", "beta"}
        # Remote hosts return the SSH-mocked payload.
        assert body["hosts"]["alpha"] == fake_payload
        assert body["hosts"]["beta"] == fake_payload


def test_api_plugins_host_all_per_host_error_envelope() -> None:
    """Failed hosts get an `error` key — fan-out never raises."""
    cfg = HarbormasterConfig(
        hosts={"broken": HostConfig(ssh_host="broken.local")},
    )
    app = create_app(cfg)
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=255,
            stderr="ssh: Could not resolve hostname broken.local",
        ),
    ), TestClient(app) as client:
        r = client.get("/api/plugins?host=all")
        assert r.status_code == 200
        body = r.json()
        assert "error" in body["hosts"]["broken"]
        assert body["hosts"]["broken"]["plugins"] == []


# -- /api/config/diff?host=<name> ----------------------------------


def test_api_config_diff_returns_unified_diff(tmp_path: Path) -> None:
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    app = create_app(cfg)
    remote_text = "[server]\nname = 'alpha'\n"
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=remote_text),
    ), TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha")
        assert r.status_code == 200
        body = r.json()
        assert body["host"] == "alpha"
        assert body["remote_path"] == "~/.config/harbormaster.toml"
        # Unified diff contains the remote-only line.
        assert "name = 'alpha'" in body["diff"]


def test_api_config_diff_empty_when_local_and_remote_match(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """When local and remote text are byte-identical, diff is empty."""
    local_path = tmp_path / "harbormaster.toml"
    local_text = "[server]\nname = 'shared'\n"
    local_path.write_text(local_text)
    monkeypatch.chdir(tmp_path)
    # _config_search_paths checks Path.cwd() / .harbormaster.toml first;
    # we name our file accordingly.
    (tmp_path / ".harbormaster.toml").write_text(local_text)

    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    app = create_app(cfg)
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=local_text),
    ), TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha")
        assert r.status_code == 200
        body = r.json()
        assert body["diff"] == ""


def test_api_config_diff_404_when_host_unknown() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/config/diff?host=missing")
        assert r.status_code == 404


def test_api_config_diff_remote_error_propagated() -> None:
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    app = create_app(cfg)
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=255,
            stderr="ssh: connect to host alpha.local port 22: Connection refused",
        ),
    ), TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha")
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert "Connection refused" in body["error"]


# -- UI wiring (template smoke) -----------------------------------


def test_dashboard_template_has_all_option_in_host_dropdown() -> None:
    body = _read_template("dashboard.html")
    assert 'value="all"' in body
    # Comment hint / Alpine wiring.
    assert "pluginsAllHosts" in body


def test_dashboard_template_has_compare_config_button() -> None:
    body = _read_template("dashboard.html")
    assert "Compare config" in body
    assert "loadConfigDiff()" in body


def test_dashboard_template_renders_per_host_summary_panel() -> None:
    body = _read_template("dashboard.html")
    assert "Per-host summary:" in body
    assert "x-for=\"(payload, name) in (pluginsAllHosts || {})\"" in body


def test_dashboard_template_renders_config_diff_panel() -> None:
    body = _read_template("dashboard.html")
    assert "configDiffOpen" in body
    assert "Config diff: local →" in body
    assert "configDiff" in body
