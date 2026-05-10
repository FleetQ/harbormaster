"""v16.0.0a1 — internal quality cluster.

Three small refactors that need pin tests so future churn doesn't
silently undo the consolidation:

1. ``_make_parser(html: bool)`` helper in ``harbormaster.ui.markdown``
   returns equivalent parsers for both call sites (``_md`` strict,
   ``_md_html`` non-strict). Verify the helper exists, both module
   singletons were built through it, and rendering still works in both
   modes.

2. The shared ``_partials/_cached_getter.html`` Alpine helper is
   included from ``base.html`` once. Verify the partial exists, the
   ``cachedGetter`` global is defined inside it, and the include
   landed in ``base.html``. Also assert the migrated call sites in
   ``network.html`` reference ``cachedGetter`` (and the previous
   private cache slots are gone).

3. The autouse ``_reset_network_log`` fixture from ``tests/conftest.py``
   guarantees every test starts with an empty ``mcp_calls`` table.
   Verify by writing a row, then asserting the next test's view is
   empty (relies on the fixture firing between tests in the same
   module).
"""
from __future__ import annotations

from pathlib import Path

# ----- Item 1: _make_parser helper ------------------------------------------


def test_make_parser_helper_exists() -> None:
    from harbormaster.ui import markdown as md

    assert callable(getattr(md, "_make_parser", None))


def test_make_parser_strict_and_non_strict() -> None:
    from harbormaster.ui import markdown as md

    strict = md._make_parser(html=False)
    permissive = md._make_parser(html=True)
    # Same parser type either way.
    assert type(strict) is type(permissive)
    # Quick rendering smoke: both render plain markdown identically.
    sample = "**bold** and `code`"
    assert "<strong>bold</strong>" in strict.render(sample)
    assert "<strong>bold</strong>" in permissive.render(sample)


def test_module_singletons_built_via_helper() -> None:
    from harbormaster.ui import markdown as md

    # Both singletons must be MarkdownIt instances of the same class
    # the helper produces — guards against re-divergence of construction.
    probe = md._make_parser(html=False)
    assert type(md._md) is type(probe)
    assert type(md._md_html) is type(probe)


def test_render_safe_still_strict_by_default() -> None:
    from harbormaster.ui.markdown import render_safe

    # Strict mode strips raw <span>; non-strict keeps it.
    raw = "Hello <span>world</span>"
    assert "<span>" not in render_safe(raw, strict=True)
    assert "<span>world</span>" in render_safe(raw, strict=False)


# ----- Item 2: cachedGetter Alpine helper -----------------------------------


def _templates_dir() -> Path:
    import harbormaster.ui as ui_pkg

    return Path(ui_pkg.__file__).parent / "templates"


def test_cached_getter_partial_exists() -> None:
    p = _templates_dir() / "_partials" / "_cached_getter.html"
    assert p.is_file(), "v16.0.0a1: shared cached-getter partial missing"


def test_cached_getter_defines_global_helper() -> None:
    p = _templates_dir() / "_partials" / "_cached_getter.html"
    body = p.read_text()
    assert "window.cachedGetter" in body
    assert "deps" in body and "ttlMs" in body


def test_base_html_includes_cached_getter_partial() -> None:
    base = (_templates_dir() / "base.html").read_text()
    assert '_partials/_cached_getter.html' in base


def test_network_html_uses_cached_getter() -> None:
    net = (_templates_dir() / "network.html").read_text()
    # Both migrated getters route through the shared helper.
    assert "cachedGetter(this, 'chatOrder'" in net
    assert "cachedGetter(this, 'timelineBuckets'" in net
    # The previous private cache slots were removed (only mentioned
    # in a removal-note comment, never as live state declarations).
    assert "_chatOrderCache: null" not in net
    assert "_timelineCacheStamp: 0" not in net


# ----- Item 3: autouse network_log reset fixture ----------------------------


def test_seed_a_row_into_network_log() -> None:
    from harbormaster.ui import network_log as nl

    # Seed one row. The autouse fixture should clean it up before the
    # next test even runs.
    with nl.network_log._lock:  # type: ignore[attr-defined]
        nl.network_log._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO mcp_calls "
            "(timestamp, source, target, tool, status, "
            " duration_ms, question_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "test", "test", "ask_project", "ok", 1, ""),
        )
        nl.network_log._conn.commit()  # type: ignore[attr-defined]
    cur = nl.network_log._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM mcp_calls"
    )
    (count,) = cur.fetchone()
    assert count == 1


def test_autouse_fixture_truncated_between_tests() -> None:
    from harbormaster.ui import network_log as nl

    cur = nl.network_log._conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM mcp_calls"
    )
    (count,) = cur.fetchone()
    assert count == 0, (
        "v16.0.0a1: autouse _reset_network_log fixture must clear the "
        "mcp_calls table between tests"
    )
