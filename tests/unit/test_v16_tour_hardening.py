"""v16.0.0a3 — tour wizard hardening.

Two carry-overs:

1. ``data-tour-step="N"`` markup attrs replace the v15.a6 fragile
   CSS selector anchors. The dashboard tour preferentially looks up
   ``[data-tour-step="..."]`` first; the v15.a6 selector survives as
   a `legacy:` fallback so a template refactor doesn't silently
   break a step.

2. Network-page tour with three steps (graph view / filter dropdown
   / timeline toggle) wired to the same `data-tour-step` discipline.
   Gated by a separate localStorage key so one tour does not block
   the other.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "harbormaster" / "ui" / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


# ---- Item 1: data-tour-step on dashboard anchors --------------------------


def test_dashboard_anchors_carry_data_tour_step_attrs() -> None:
    body = _read("dashboard.html")
    # KPI strip cell.
    assert 'data-tour-step="kpi-strip"' in body
    # Ask form (per-card collapsible section).
    assert 'data-tour-step="ask-form"' in body
    # First project card carries the memories anchor.
    assert "idx === 0 ? 'memories' : null" in body


def test_base_html_anchors_carry_data_tour_step_attrs() -> None:
    body = _read("base.html")
    assert 'data-tour-step="sidebar"' in body
    assert 'data-tour-step="palette"' in body


def test_dashboard_tour_uses_tour_step_lookup_first() -> None:
    body = _read("dashboard.html")
    # The new lookup helper queries `[data-tour-step="..."]` first.
    assert 'document.querySelector(`[data-tour-step="${step.tourStep}"]`)' in body
    # Each step lists `tourStep` AND a `legacy` fallback.
    for name in ("kpi-strip", "sidebar", "ask-form", "palette", "memories"):
        assert f"tourStep: '{name}'" in body
    # Legacy field is preserved so a missing attr still falls through.
    assert "legacy:" in body


def test_dashboard_tour_anchor_helper_falls_through_to_legacy() -> None:
    body = _read("dashboard.html")
    # _findAnchor() must consult `step.legacy` when the data-attr
    # lookup failed — this is the safety net.
    assert "_findAnchor(step)" in body
    assert "step.legacy" in body


# ---- Item 2: /network page tour ------------------------------------------


def test_network_template_declares_network_tour_anchors() -> None:
    body = _read("network.html")
    for name in ("network-graph", "network-filter", "network-timeline"):
        assert f'data-tour-step="{name}"' in body, (
            f"v16.0.0a3: network anchor {name!r} missing"
        )


def test_network_template_wires_network_tour_factory() -> None:
    body = _read("network.html")
    assert "function networkTour()" in body
    assert "networkTour()" in body
    # Three-step plan from the brief.
    assert "title: 'Graph view'" in body
    assert "title: 'Filter dropdown'" in body
    assert "title: 'Timeline toggle'" in body


def test_network_tour_gated_by_separate_localstorage_key() -> None:
    body = _read("network.html")
    # Distinct key from `hm-tour-completed` (dashboard) so the two
    # don't collide.
    assert "hm-network-tour-completed" in body
    # And the dashboard one must NOT be referenced inside network.html.
    # (That would mean a copy-paste regression collapsing the two.)
    assert "hm-tour-completed" not in body.replace("hm-network-tour-completed", "")


def test_network_tour_uses_data_tour_step_anchor_lookup() -> None:
    body = _read("network.html")
    # Lookup goes through `[data-tour-step="${step.tourStep}"]`.
    assert 'document.querySelector(`[data-tour-step="${step.tourStep}"]`)' in body


def test_network_tour_force_via_query_string_works_too() -> None:
    body = _read("network.html")
    # Same `?tour=1` re-trigger as the dashboard tour, so the
    # operator only has to remember one URL flag.
    assert "params.get('tour') === '1'" in body
