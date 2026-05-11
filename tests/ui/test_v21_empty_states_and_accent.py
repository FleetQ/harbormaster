"""v21.0.0a3: empty-states polish + operator-tunable accent picker.

Pins:
  - Empty-state copy across dashboard / network / dispatcher / project_detail
    uses the canonical 3-part pattern (headline + body + CTA) instead of
    the v8 one-liner stubs.
  - Accent picker widget is mounted in the dashboard inspector with the
    Alpine factory `accentPicker()`.
  - `GET /api/settings/accent` returns the operator-configured accent
    (defaults: hue=290, chroma=0.22).
  - `PUT /api/settings/accent` validates ranges, persists to
    ``~/.config/harbormaster/config.toml`` `[ui]` section, mutates the
    live config so SSR-side `<style>` injection in base.html reflects
    the new value, and is idempotent for save+get round-trips.
  - The base.html override `<style id="hm-custom-accent">` block is
    rendered only when the current `[ui]` section differs from the
    Linear-violet baseline (zero bytes overhead for default install).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig, UIConfig
from harbormaster.ui import create_app

TEMPLATES = Path(__file__).parent.parent.parent / "src" / "harbormaster" / "ui" / "templates"


# --- Empty-state copy assertions ----------------------------------------


def test_dashboard_plugins_empty_state_polished() -> None:
    """`No entry points discovered.` v8 stub replaced with 3-part copy."""
    src = (TEMPLATES / "dashboard.html").read_text()
    # Old terse stub is gone.
    assert "No entry points discovered." not in src
    # New 3-part state present.
    assert "No plugins installed." in src
    assert 'data-empty-state="plugins.none"' in src
    assert "pip install harbormaster-plugin-" in src


def test_dashboard_recent_activity_empty_state_polished() -> None:
    """`no recent calls` plain text replaced with CTA-bearing copy."""
    src = (TEMPLATES / "dashboard.html").read_text()
    # The old plain-text stub should no longer appear as a standalone
    # leaf (`text-foreground-subtle">no recent calls</li>`).
    assert 'text-foreground-subtle">no recent calls' not in src
    assert "No recent activity." in src
    assert "ask_project" in src


def test_network_empty_state_polished() -> None:
    src = (TEMPLATES / "network.html").read_text()
    assert "No MCP traffic yet." in src
    assert 'data-empty-state="network.no-events"' in src


def test_dispatcher_empty_states_polished() -> None:
    src = (TEMPLATES / "dispatcher_trace.html").read_text()
    assert "No spans in flight." in src
    assert "No completed traces yet." in src
    assert 'data-empty-state="dispatcher.no-active"' in src
    assert 'data-empty-state="dispatcher.no-traces"' in src


def test_project_detail_empty_states_polished() -> None:
    src = (TEMPLATES / "project_detail.html").read_text()
    assert "No memory files yet." in src
    assert "No Q&amp;A history yet." in src
    assert 'data-empty-state="qa-history.empty"' in src


# --- Accent picker template assertions ----------------------------------


def test_accent_picker_widget_mounted_in_dashboard_inspector() -> None:
    """The accent picker `<details>` element is present in the dashboard
    inspector block with the canonical Alpine factory + GET/PUT plumbing."""
    src = (TEMPLATES / "dashboard.html").read_text()
    assert 'data-inspector-accent' in src
    assert "accentPicker()" in src
    assert "function accentPicker()" in src
    # The factory exposes preview / save / reset.
    assert "preview()" in src
    assert "applyToDOM()" in src
    assert "/api/settings/accent" in src


def test_base_html_emits_accent_override_only_when_non_default() -> None:
    """base.html guards the `<style id="hm-custom-accent">` block behind
    a Jinja conditional that compares against the violet baseline."""
    src = (TEMPLATES / "base.html").read_text()
    assert 'id="hm-custom-accent"' in src
    assert "ui_accent_hue != 290" in src
    assert "ui_accent_chroma != 0.22" in src
    # The override actually rewrites the canonical Tailwind tokens.
    assert "--color-accent-strong: oklch" in src
    assert "--color-accent: oklch" in src


# --- Backend endpoint assertions ----------------------------------------


def _client(tmp_path: Path, ui: UIConfig | None = None) -> TestClient:
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        ui=ui or UIConfig(),
    )
    return TestClient(create_app(cfg))


def test_get_accent_returns_defaults(tmp_path: Path) -> None:
    r = _client(tmp_path).get("/api/settings/accent")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hue"] == 290.0
    assert body["chroma"] == 0.22


def test_get_accent_returns_configured_values(tmp_path: Path) -> None:
    ui = UIConfig(accent_hue=140.0, accent_chroma=0.15)
    r = _client(tmp_path, ui=ui).get("/api/settings/accent")
    assert r.status_code == 200
    assert r.json() == {"hue": 140.0, "chroma": 0.15}


def test_put_accent_rejects_hue_out_of_range(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.put("/api/settings/accent", json={"hue": 400, "chroma": 0.2})
    assert r.status_code == 400
    assert "hue" in r.json()["error"]


def test_put_accent_rejects_chroma_out_of_range(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.put("/api/settings/accent", json={"hue": 290, "chroma": 0.5})
    assert r.status_code == 400
    assert "chroma" in r.json()["error"]


def test_put_accent_rejects_negative_hue(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.put("/api/settings/accent", json={"hue": -1, "chroma": 0.2})
    assert r.status_code == 400


def test_put_accent_rejects_invalid_payload(tmp_path: Path) -> None:
    """FastAPI's dict[str, float] body schema rejects non-numeric values
    with 422 before they reach the handler; either 400 or 422 is fine."""
    client = _client(tmp_path)
    r = client.put("/api/settings/accent", json={"hue": "not-a-number"})
    assert r.status_code in (400, 422)


def test_put_accent_persists_and_round_trips(
    tmp_path: Path, monkeypatch
) -> None:
    """Save → GET returns saved values, AND the TOML on disk matches."""
    fake_xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_xdg))
    client = _client(tmp_path)
    r = client.put(
        "/api/settings/accent",
        json={"hue": 150.0, "chroma": 0.18},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"hue": 150.0, "chroma": 0.18, "ok": True}

    toml_path = fake_xdg / "harbormaster" / "config.toml"
    assert toml_path.is_file()
    parsed = tomllib.loads(toml_path.read_text())
    assert parsed["ui"]["accent_hue"] == 150.0
    assert parsed["ui"]["accent_chroma"] == 0.18

    # Live config mutation — subsequent GET returns the new values.
    r2 = client.get("/api/settings/accent")
    assert r2.status_code == 200
    assert r2.json() == {"hue": 150.0, "chroma": 0.18}


def test_put_accent_preserves_other_top_level_tables(
    tmp_path: Path, monkeypatch
) -> None:
    """Pre-existing top-level tables (e.g. `[server]`) must survive
    the atomic rewrite."""
    fake_xdg = tmp_path / "xdg"
    cfg_path = fake_xdg / "harbormaster" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        '[server]\nbind_host = "127.0.0.1"\n', encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_xdg))
    client = _client(tmp_path)
    r = client.put(
        "/api/settings/accent",
        json={"hue": 30.0, "chroma": 0.10},
    )
    assert r.status_code == 200, r.text
    parsed = tomllib.loads(cfg_path.read_text())
    assert parsed["server"]["bind_host"] == "127.0.0.1"
    assert parsed["ui"]["accent_hue"] == 30.0
    assert parsed["ui"]["accent_chroma"] == 0.10


# --- UIConfig pydantic model --------------------------------------------


def test_ui_config_defaults_match_violet_baseline() -> None:
    ui = UIConfig()
    assert ui.accent_hue == 290.0
    assert ui.accent_chroma == 0.22


def test_ui_config_rejects_unknown_keys() -> None:
    """`_FORBID_EXTRA` should bite — typos in operator config surface
    as ValidationError instead of being silently ignored."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        UIConfig(accent_hue=200.0, bogus="x")  # type: ignore[call-arg]
