"""v14.0.0a6 — cross-host plugin discovery: SSH-mocked + endpoint + UI."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HostConfig
from harbormaster.plugins import query_remote_plugins
from harbormaster.plugins_cli import _list_payload
from harbormaster.plugins_cli import main as plugins_main
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


# -- plugins_cli --json ----------------------------------------------


def test_plugins_cli_json_emits_canonical_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text("[plugins]\nenabled = false\n")
    rc = plugins_main(["list", "--config", str(cfg), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # Schema: {enabled, allow, discovered_count, plugins}
    assert set(payload.keys()) >= {"enabled", "allow", "discovered_count", "plugins"}
    assert payload["enabled"] is False
    assert isinstance(payload["allow"], list)
    assert isinstance(payload["plugins"], list)


def test_plugins_cli_text_format_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --json, the text format must contain the v2.0.1 markers."""
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text("[plugins]\nenabled = false\n")
    rc = plugins_main(["list", "--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[plugins].enabled = False" in out


def test_list_payload_helper_returns_dict(tmp_path: Path) -> None:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text("[server]\n")
    payload = _list_payload(cfg)
    assert isinstance(payload, dict)
    assert "discovered_count" in payload


# -- query_remote_plugins (SSH-mocked) -------------------------------


def _fake_completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ssh", "fake"], returncode=returncode,
        stdout=stdout, stderr=stderr,
    )


def test_query_remote_plugins_returns_remote_payload() -> None:
    host = HostConfig(ssh_host="alpha.local")
    fake_payload: dict[str, Any] = {
        "enabled": True, "allow": ["foo-plugin"],
        "discovered_count": 1,
        "plugins": [{"status": "loaded", "dist_name": "foo-plugin",
                     "entry_point": "foo"}],
    }
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=json.dumps(fake_payload)),
    ):
        result = query_remote_plugins(host)
    assert result == fake_payload


def test_query_remote_plugins_handles_ssh_timeout() -> None:
    from harbormaster.ssh import SshTimeoutError

    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        side_effect=SshTimeoutError("SSH to 'alpha.local' exceeded 120s"),
    ):
        result = query_remote_plugins(host)
    assert result["plugins"] == []
    assert "exceeded" in result["error"]


def test_query_remote_plugins_handles_ssh_layer_failure() -> None:
    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=255,
            stderr="ssh: connect to host alpha.local port 22: Connection refused",
        ),
    ):
        result = query_remote_plugins(host)
    assert result["plugins"] == []
    assert "Connection refused" in result["error"]


def test_query_remote_plugins_handles_remote_nonzero_exit() -> None:
    """SSH succeeded but remote command returned non-zero (e.g.
    binary not installed)."""
    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(
            returncode=127,
            stderr="bash: harbormaster-mcp: command not found",
        ),
    ):
        result = query_remote_plugins(host)
    assert result["plugins"] == []
    assert "command not found" in result["error"]


def test_query_remote_plugins_handles_invalid_json() -> None:
    host = HostConfig(ssh_host="alpha.local")
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout="not json"),
    ):
        result = query_remote_plugins(host)
    assert result["plugins"] == []
    assert "non-JSON" in result["error"]


# -- /api/plugins?host=… endpoint -------------------------------------


def test_api_plugins_local_unchanged_when_host_unset() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/plugins")
        assert r.status_code == 200
        body = r.json()
        # Existing v2.1.0a1 shape — no 'error' key on the local path.
        assert "discovered_count" in body
        assert "error" not in body


def test_api_plugins_local_when_host_equals_local() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/plugins?host=local")
        assert r.status_code == 200
        assert "error" not in r.json()


def test_api_plugins_remote_404_when_host_not_in_config() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/plugins?host=missing")
        assert r.status_code == 404
        assert "not in [hosts.*]" in r.json()["detail"]


def test_api_plugins_remote_dispatches_to_query_function() -> None:
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    fake_payload = {
        "enabled": True, "allow": ["foo"], "discovered_count": 1,
        "plugins": [{"status": "loaded", "dist_name": "foo",
                     "entry_point": "ep"}],
    }
    app = create_app(cfg)
    with TestClient(app) as client:
        with patch(
            "harbormaster.plugins.query_remote_plugins",
            return_value=fake_payload,
        ):
            r = client.get("/api/plugins?host=alpha")
        assert r.status_code == 200
        assert r.json() == fake_payload


# -- UI wiring (template smoke) --------------------------------------


def test_dashboard_plugin_card_has_host_dropdown() -> None:
    body = _read_template("dashboard.html")
    assert 'x-model="pluginHost"' in body
    assert 'aria-label="Plugin host filter"' in body
    # Default option is "local".
    assert '<option value="local">local</option>' in body


def test_dashboard_load_plugin_hosts_uses_budget_endpoint() -> None:
    body = _read_template("dashboard.html")
    # Reuses /api/hosts/budget for the host list (no new endpoint).
    assert "/api/hosts/budget" in body
    assert "loadPluginHosts" in body


def test_dashboard_load_plugins_appends_host_param() -> None:
    body = _read_template("dashboard.html")
    assert "this.pluginHost && this.pluginHost !== 'local'" in body
    assert "/api/plugins?host=" in body


def test_dashboard_renders_remote_error_envelope() -> None:
    """When the remote query returns {error: '...'}, the card surfaces
    it as a warning under the header (not as a JS exception)."""
    body = _read_template("dashboard.html")
    assert 'x-text="plugins.error"' in body
    assert 'text-warning' in body  # warning color for the error line


def test_plugin_host_state_initialised_local() -> None:
    body = _read_template("dashboard.html")
    assert "pluginHost: 'local'" in body
    assert "pluginHosts: []" in body
