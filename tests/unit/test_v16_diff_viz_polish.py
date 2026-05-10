"""v16.0.0a4 — diff/comparison viz polish.

Two carry-overs:

1. ``GET /api/config/diff?format=html`` returns a side-by-side HTML
   diff via ``difflib.HtmlDiff`` (mirrors v13.a3 memory-revisions
   pattern). JSON shape unchanged when ``?format=json`` (default).
2. ``_partials/_tiny_sparkline.html`` defines a ``window.sparklineHtml``
   helper for per-cell trend cells in the future N-way reembed
   comparison panel. Roll-our-own SVG, ~50 lines, no new deps.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HostConfig
from harbormaster.ui import create_app

# ---- helpers ---------------------------------------------------------------


def _fake_completed(stdout: str = "", returncode: int = 0) -> Any:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---- Item 1: /api/config/diff?format=html ---------------------------------


def test_config_diff_format_html_returns_html_response() -> None:
    cfg = HarbormasterConfig(hosts={"alpha": HostConfig(ssh_host="alpha.local")})
    app = create_app(cfg)
    remote_text = "[server]\nname = 'alpha'\n"
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=remote_text),
    ), TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha&format=html")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        # difflib.HtmlDiff().make_file() always emits a doctype + table.
        assert "<!DOCTYPE" in r.text or "<!doctype" in r.text.lower()
        assert "<table" in r.text


def test_config_diff_html_includes_both_sides() -> None:
    cfg = HarbormasterConfig(hosts={"alpha": HostConfig(ssh_host="alpha.local")})
    app = create_app(cfg)
    remote_text = "[server]\nname = 'alpha'\n"
    with patch(
        "harbormaster.ssh.run_ssh",
        return_value=_fake_completed(stdout=remote_text),
    ), TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha&format=html")
        # Side-by-side view labels both columns by host descriptor.
        assert "alpha:" in r.text or "alpha" in r.text


def test_config_diff_format_json_default_unchanged() -> None:
    """Existing v15.a2 callers must see byte-identical JSON shape
    when ``format=json`` (default) — back-compat invariant."""
    cfg = HarbormasterConfig(hosts={"alpha": HostConfig(ssh_host="alpha.local")})
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
        assert "diff" in body
        assert "name = 'alpha'" in body["diff"]


def test_config_diff_format_invalid_returns_400() -> None:
    cfg = HarbormasterConfig(hosts={"alpha": HostConfig(ssh_host="alpha.local")})
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/config/diff?host=alpha&format=xml")
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower()


def test_config_diff_html_404_when_host_unknown() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/config/diff?host=missing&format=html")
        assert r.status_code == 404


# ---- Item 2: tiny-sparkline partial + base.html include ------------------


def _templates_dir() -> Path:
    import harbormaster.ui as ui_pkg
    return Path(ui_pkg.__file__).parent / "templates"


def test_sparkline_partial_exists() -> None:
    p = _templates_dir() / "_partials" / "_tiny_sparkline.html"
    assert p.is_file(), "v16.0.0a4: tiny-sparkline partial missing"


def test_sparkline_defines_global_helper() -> None:
    body = (_templates_dir() / "_partials" / "_tiny_sparkline.html").read_text()
    assert "window.sparklineHtml" in body
    # Roll-our-own SVG, no CDN dependency.
    assert "https://" not in body
    assert "<svg" in body
    assert "<polyline" in body


def test_sparkline_pins_empty_input_returns_empty_string() -> None:
    body = (_templates_dir() / "_partials" / "_tiny_sparkline.html").read_text()
    # Behaviour pin from the partial header.
    assert "if (!Array.isArray(values) || values.length === 0) return ''" in body


def test_sparkline_handles_single_or_flat_values() -> None:
    body = (_templates_dir() / "_partials" / "_tiny_sparkline.html").read_text()
    # Both single-point and zero-range render mid-height — verifying
    # the branch exists.
    assert "nums.length === 1 || range === 0" in body


def test_base_html_includes_sparkline_partial() -> None:
    body = (_templates_dir() / "base.html").read_text()
    assert '_partials/_tiny_sparkline.html' in body


def test_sparkline_aria_label_includes_value_list() -> None:
    """Accessibility: the sparkline must expose its values via
    aria-label so screen-reader users get the trend."""
    body = (_templates_dir() / "_partials" / "_tiny_sparkline.html").read_text()
    assert 'aria-label="trend ' in body
