"""Static safety audit for Alpine `x-show` + measure-dependent libs (v7.0.0a2).

The v6.0.0 → v6.0.2 graph-render bug class came from wrapping the
`<pre class="mermaid">` element inside `x-show="!loading"`. While
`x-show` only toggles `display: none`, libraries that *measure* the
element at init time (Mermaid via getBBox(), chart libs, sortable,
virtual-scrollers) see the hidden container as 0×0 and either bail
out or render with placeholder dimensions.

The fix in v6.0.1/v6.0.2 was to flip the loading flag BEFORE calling
the renderer, so by the time it measures, the container is visible.
That fix lives in the JS, not the template — which means the next
template edit can reintroduce the bug.

This audit walks every template via html.parser, tracks which elements
carry `x-show`, and flags any whose descendant subtree contains a
measure-dependent class/element unless explicitly allowlisted.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)

# Class tokens that mark a measure-dependent library element.
# When any descendant of an x-show wrapper carries one of these,
# the wrapper risks the v6.0.0/6.0.1/6.0.2 bug class.
MEASURE_DEPENDENT_CLASSES = frozenset(
    {
        "mermaid",        # Mermaid: measures via getBBox()
        "chart",          # generic chart libs (Chart.js, etc.)
        "sortable",       # SortableJS measures bounding rects
        "virtual-list",   # virtual scrollers
        "virtual-scroll",
    }
)

# Allowlist: known-safe (template, x-show expression) pairs.
# Each entry must be accompanied by a code comment explaining why
# the JS guarantees the wrapper is unhidden BEFORE the library
# measures.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    # dashboard.html ProjectGraph wrapper:
    # The Alpine scope flips this.graphLoading = false BEFORE calling
    # mermaid.run(). See dashboard.html ~line 1014 comment block, plus
    # sprint retros v6.0.1 + v6.0.2 + v7.0.0a1. The Playwright SVG-
    # render assertion (test_dashboard_graph_renders_with_real_viewbox)
    # is the runtime backstop.
    ("dashboard.html", "!graphLoading"),
)


# Self-closing/void HTML elements — we never push these on the stack.
VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)


class _TemplateScanner(HTMLParser):
    """Tracks element stack + records x-show wrappers + their subtree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Stack entry: dict with keys 'tag', 'x_show', 'matched'
        self._stack: list[dict[str, object]] = []
        # Findings: (x_show_expr, hit_class)
        self.findings: list[tuple[str, str]] = []

    def _check_for_measure_class(
        self, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = dict(attrs)
        cls = (attr_map.get("class") or "").split()
        hit = next((c for c in cls if c in MEASURE_DEPENDENT_CLASSES), None)
        if hit is None:
            return
        for frame in self._stack:
            if frame.get("x_show") is not None and not frame.get("matched"):
                expr = frame["x_show"]
                assert isinstance(expr, str)
                self.findings.append((expr, hit))
                frame["matched"] = True

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        # Check current element's class FIRST so it's evaluated against
        # already-open ancestors (not itself).
        self._check_for_measure_class(attrs)

        if tag.lower() in VOID_ELEMENTS:
            return
        # Push frame so children can detect ancestor x-show wrappers.
        attr_map = dict(attrs)
        x_show = attr_map.get("x-show")
        self._stack.append({"tag": tag.lower(), "x_show": x_show, "matched": False})

    def handle_endtag(self, tag: str) -> None:
        # Pop until we drop the matching open tag (templates are
        # imperfect; this lenient pop tolerates Jinja control flow
        # that the html.parser doesn't fully understand).
        target = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == target:
                del self._stack[i:]
                return

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        # Self-closing — same logic as start, but never push.
        self._check_for_measure_class(attrs)


def _scan_template(path: Path) -> list[tuple[str, str]]:
    """Return list of (x_show_expr, hit_class) tuples."""
    scanner = _TemplateScanner()
    scanner.feed(path.read_text(encoding="utf-8"))
    return scanner.findings


def test_no_unallowlisted_x_show_around_measure_dependent_libs() -> None:
    """Catch the v6.0.0/v6.0.1/v6.0.2 graph-render bug class statically.

    Any element with `x-show="..."` whose descendant subtree contains
    a measure-dependent library element is flagged unless the
    (template, expression) pair is in ALLOWLIST.
    """
    assert TEMPLATE_DIR.is_dir(), f"templates not found at {TEMPLATE_DIR}"

    failures: list[str] = []
    for tpl in sorted(TEMPLATE_DIR.rglob("*.html")):
        rel_name = tpl.name
        for expr, hit_class in _scan_template(tpl):
            if (rel_name, expr) in ALLOWLIST:
                continue
            failures.append(
                f"{rel_name}: x-show=\"{expr}\" wraps a measure-dependent "
                f"library element (class={hit_class!r}). "
                f"This is the v6.0.0/v6.0.1/v6.0.2 bug class — Alpine "
                f"x-show only toggles display:none; the library will "
                f"measure the hidden element at 0x0 and render a "
                f"placeholder. Either: (a) restructure to flip the "
                f"flag BEFORE the renderer runs and add this "
                f"(file, expr) pair to ALLOWLIST in this test with "
                f"a comment explaining why it's safe; or (b) move "
                f"the measure-dependent element out of the x-show "
                f"subtree."
            )

    if failures:
        pytest.fail(
            "Template safety audit found unallowlisted x-show + measure-"
            "dependent library patterns:\n\n" + "\n\n".join(failures)
        )


def test_allowlist_entries_are_actually_present() -> None:
    """Every ALLOWLIST entry must match a real pattern in the templates.

    Prevents stale allowlist entries from accumulating across refactors —
    when the wrapping x-show is removed (i.e. the bug class is no longer
    possible), the allowlist entry should be removed too.
    """
    for filename, expr in ALLOWLIST:
        tpl = TEMPLATE_DIR / filename
        assert tpl.exists(), f"allowlist references missing template {filename}"
        text = tpl.read_text(encoding="utf-8")
        needle = f'x-show="{expr}"'
        assert needle in text, (
            f"stale ALLOWLIST entry: {filename} no longer contains "
            f'{needle!r} — remove the entry from ALLOWLIST.'
        )


def test_scanner_finds_a_real_pattern_in_dashboard() -> None:
    """Sanity: the scanner must detect the known safe pattern in
    dashboard.html. If it doesn't, the scanner is broken (false
    negatives are silent — defenders need to know the test runs)."""
    findings = _scan_template(TEMPLATE_DIR / "dashboard.html")
    exprs = {f[0] for f in findings}
    assert "!graphLoading" in exprs, (
        "scanner failed to find the !graphLoading wrapper in "
        "dashboard.html — the html.parser walk is broken or the "
        "template was restructured (in which case remove the "
        "ALLOWLIST entry too)."
    )
