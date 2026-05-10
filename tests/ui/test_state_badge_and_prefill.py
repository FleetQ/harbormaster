"""v11.0.0a4: stateBadge unification + ?q= URL pre-fill.

Tests cover:
  - The shared `_state_badge.html` partial is loaded on every page
    (via base.html include).
  - The helper exposes `window.harbormaster.stateBadgeHtml` and the
    color allowlist (emerald / amber / rose / cyan / gray).
  - The network status pill consumes the helper instead of inline
    text.
  - Project_detail's askForm Alpine factory has an init() method
    that reads `?q=` from the URL.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- shared helper rendered on every page ----------------------------


def test_state_badge_helper_present_on_dashboard(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "harbormaster.stateBadgeHtml" in body
    # Color allowlist baked into the helper (avoids dynamic class
    # generation that Tailwind would purge).
    assert "bg-emerald-900/50" in body
    assert "bg-amber-900/50" in body
    assert "bg-rose-900/50" in body
    assert "bg-cyan-900/50" in body
    assert "bg-gray-800" in body


def test_state_badge_helper_present_on_project_detail(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    assert "harbormaster.stateBadgeHtml" in r.text


def test_state_badge_helper_present_on_network(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/network")
    assert r.status_code == 200
    body = r.text
    # Helper present.
    assert "harbormaster.stateBadgeHtml" in body
    # Network status now consumes it.
    assert "stateBadgeHtml({" in body
    # Colors signal live (emerald) + offline (amber).
    assert "color: 'emerald'" in body
    assert "color: 'amber'" in body


def test_state_badge_helper_idempotent_load() -> None:
    """The IIFE checks for an existing helper before re-defining it.

    Belt-and-braces: protects against an accidental double-include
    (e.g. base.html + a layout partial both pulling _state_badge.html
    in)."""
    src_path = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_state_badge.html"
    )
    text = src_path.read_text(encoding="utf-8")
    assert "if (window.harbormaster && window.harbormaster.stateBadgeHtml) return" in text


def test_state_badge_renders_data_state_attribute() -> None:
    """The helper output includes a `data-state="<state>"` attr so
    e2e tests / future unit tests can assert on the badge state
    structurally instead of by visible text."""
    src_path = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_state_badge.html"
    )
    text = src_path.read_text(encoding="utf-8")
    assert "data-state=" in text


# -- ?q= URL pre-fill --------------------------------------------------


def test_ask_form_factory_has_init_with_q_prefill(tmp_path: Path) -> None:
    """The askForm component reads `?q=` and assigns it to .question."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # The init() method body, with the searchParams.get('q') call.
    assert "searchParams.get('q')" in body
    assert "this.question = q" in body


def test_ask_form_factory_init_present_on_dashboard(tmp_path: Path) -> None:
    """Dashboard's per-card askForm uses the same factory; init()
    runs there too without an explicit x-init."""
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/")
    body = r.text
    # Dashboard includes the factory partial → init() is reachable.
    assert "function askForm" in body
    assert "searchParams.get('q')" in body


def test_q_param_present_in_cmdk_action_url(tmp_path: Path) -> None:
    """The cmd-K dynamic-action that the operator uses to build a
    pre-filled URL still includes `?q=<question>` — closing the loop
    with the receiving askForm's init()."""
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/")
    body = r.text
    assert "'?q=' + encodeURIComponent(question)" in body
