"""Empty-state surface audit for v8.0.0a3.

Phase 3 of the v8 UI polish line ships the canonical 3-part empty
state pattern (headline + secondary explanation + CTA) on every
"nothing yet" surface. This test snapshots the markup for each
surface — drift breaks the test before drift hits production.

Surfaces audited (each carries `data-empty-state="<surface>"`):
  - dashboard.no-projects
  - recall.no-matches
  - reembed.no-runs
  - trajectory.no-entries
  - fanout.no-selection

For each: the surface block must contain
  * a `font-bold text-foreground` headline (the 3-part top line —
    semantic-token form post-v13.0.0a2 utility migration)
  * a `text-xs text-foreground-muted` body line (the secondary
    explanation, semantic-token form)
  * a CTA — either an `<a href=` link or a `<button` with
    `aria-label`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


SURFACES: list[tuple[str, str]] = [
    ("dashboard.html", "dashboard.no-projects"),
    ("dashboard.html", "recall.no-matches"),
    ("dashboard.html", "reembed.no-runs"),
    ("project_detail.html", "trajectory.no-entries"),
    ("fan_out.html", "fanout.no-selection"),
]


def _surface_block(template_name: str, surface_id: str) -> str:
    """Return the substring containing the named empty-state block."""
    src = (TEMPLATE_DIR / template_name).read_text()
    needle = f'data-empty-state="{surface_id}"'
    i = src.find(needle)
    assert i != -1, f"surface {surface_id!r} missing in {template_name}"
    # Locate the enclosing <div ...> that owns the data-empty-state attr.
    start = src.rfind("<div", 0, i)
    # The block ends at the matching </div>. Greedy is safe here because
    # the empty-state divs don't nest other <div>s in our markup.
    end = src.find("</div>", i)
    assert start != -1 and end != -1
    return src[start : end + len("</div>")]


@pytest.mark.parametrize("template,surface_id", SURFACES, ids=[s for _, s in SURFACES])
def test_empty_state_has_headline(template: str, surface_id: str) -> None:
    block = _surface_block(template, surface_id)
    assert "font-bold text-foreground" in block, (
        f"{surface_id}: missing canonical headline class"
    )


@pytest.mark.parametrize("template,surface_id", SURFACES, ids=[s for _, s in SURFACES])
def test_empty_state_has_body(template: str, surface_id: str) -> None:
    block = _surface_block(template, surface_id)
    # The body line uses one of two canonical sizes: text-xs or text-[11px].
    assert (
        "text-xs text-foreground-muted" in block
        or "text-[11px] text-foreground-muted" in block
    ), (
        f"{surface_id}: missing canonical body class"
    )


@pytest.mark.parametrize("template,surface_id", SURFACES, ids=[s for _, s in SURFACES])
def test_empty_state_has_cta(template: str, surface_id: str) -> None:
    block = _surface_block(template, surface_id)
    # Either an anchor link or a button-with-aria-label is acceptable.
    has_link = "<a href=" in block
    has_button = "<button" in block and "aria-label=" in block
    assert has_link or has_button, (
        f"{surface_id}: missing CTA (need either <a href=> or <button aria-label=>)"
    )


@pytest.mark.parametrize("template,surface_id", SURFACES, ids=[s for _, s in SURFACES])
def test_empty_state_carries_role_status(template: str, surface_id: str) -> None:
    block = _surface_block(template, surface_id)
    assert 'role="status"' in block, (
        f"{surface_id}: empty-state must declare role=status (SR announces politely)"
    )


@pytest.mark.parametrize("template,surface_id", SURFACES, ids=[s for _, s in SURFACES])
def test_empty_state_binds_aria_hidden(template: str, surface_id: str) -> None:
    block = _surface_block(template, surface_id)
    assert ":aria-hidden=" in block, (
        f"{surface_id}: empty-state must bind :aria-hidden to its x-show"
    )


def test_empty_state_partial_exists() -> None:
    """The shared partial must remain available for future surfaces."""
    partial = TEMPLATE_DIR / "_partials" / "_empty_state.html"
    assert partial.exists(), "_partials/_empty_state.html must exist"
    text = partial.read_text()
    assert "{{ es_headline }}" in text
    assert "{{ es_body }}" in text
