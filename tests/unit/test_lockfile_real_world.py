"""Real-world lockfile fixture tests (v4.0.0a1).

Asserts the v3.0.0a3 pnpm + yarn parsers handle quirks taken from
actual OSS projects (React, Next.js, Vue, etc.). Fixtures live in
tests/fixtures/lockfiles/ and are realistic snippets — not full
lockfiles, but representative of the format variants that appeared
in the wild and surprised the canonical-format unit tests.
"""
from __future__ import annotations

from pathlib import Path

from harbormaster.graph.lockfile import parse_pnpm_lock, parse_yarn_lock

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "lockfiles"


# --- pnpm v6 (React/Vue style) -------------------------------------------


def test_pnpm_v6_react_style_extracts_runtime_packages() -> None:
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-react-style.yaml")
    assert pkgs is not None
    # Core packages from the importer must appear.
    assert "react" in pkgs
    assert "react-dom" in pkgs
    assert "@types/react" in pkgs
    assert "@types/react-dom" in pkgs
    assert "typescript" in pkgs
    # Transitive deps should also appear (they're in the packages: map).
    assert "loose-envify" in pkgs
    assert "scheduler" in pkgs
    assert "csstype" in pkgs


def test_pnpm_v6_react_style_handles_peerdep_suffix() -> None:
    """pnpm v6 keys can carry peerDependency suffix like
    /react-dom@18.2.0(react@18.2.0): — parser must extract just the name."""
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-react-style.yaml")
    assert pkgs is not None
    # The peerdep suffix variant must NOT leak as a separate package name.
    assert "react-dom" in pkgs
    bad_keys = [p for p in pkgs if "(" in p or ")" in p]
    assert bad_keys == [], f"peerdep parens leaked into: {bad_keys}"


def test_pnpm_v6_handles_scoped_packages_in_real_lockfile() -> None:
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-react-style.yaml")
    assert pkgs is not None
    scoped = [p for p in pkgs if p.startswith("@")]
    assert "@types/react" in scoped
    assert "@types/react-dom" in scoped
    assert "@types/scheduler" in scoped
    assert "@types/prop-types" in scoped
    assert "@babel/runtime" in scoped


# --- pnpm v9 (Next.js style) ---------------------------------------------


def test_pnpm_v9_next_style_extracts_packages() -> None:
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-v9-style.yaml")
    assert pkgs is not None
    assert "next" in pkgs
    assert "react" in pkgs
    assert "react-dom" in pkgs
    assert "@next/env" in pkgs
    assert "@swc/helpers" in pkgs


def test_pnpm_v9_ignores_snapshots_block() -> None:
    """v9 has both `packages:` and `snapshots:` top-level sections.
    The parser must stop at `snapshots:` (a top-level dedent) — not
    pull in dependencies-of-dependencies as separate package keys."""
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-v9-style.yaml")
    assert pkgs is not None
    # @swc/counter and tslib live ONLY inside snapshots[]'s nested
    # dependencies block, not in the packages: map. Parser must not
    # promote them to first-class.
    assert "@swc/counter" not in pkgs
    assert "tslib" not in pkgs


# --- yarn v1 (classic) ---------------------------------------------------


def test_yarn_v1_extracts_top_level_packages() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-v1-style.lock")
    assert pkgs is not None
    assert "react" in pkgs
    assert "react-dom" in pkgs
    assert "@types/react" in pkgs
    assert "@types/node" in pkgs
    assert "@types/prop-types" in pkgs
    assert "loose-envify" in pkgs
    assert "scheduler" in pkgs


def test_yarn_v1_handles_multi_selector_keys() -> None:
    """yarn v1 allows comma-separated selectors sharing one resolved
    entry: `"loose-envify@^1.1.0", "loose-envify@^1.4.0":`. Both
    selectors must yield the same package name once."""
    pkgs = parse_yarn_lock(FIXTURES / "yarn-v1-style.lock")
    assert pkgs is not None
    # Should appear exactly once (set semantics).
    assert "loose-envify" in pkgs


def test_yarn_v1_skips_comment_lines() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-v1-style.lock")
    assert pkgs is not None
    # Comment lines like "# yarn lockfile v1" must not leak as package names.
    bad = [p for p in pkgs if p.startswith("#") or "lockfile" in p]
    assert bad == [], f"comment leaked as package: {bad}"


# --- yarn berry ----------------------------------------------------------


def test_yarn_berry_extracts_npm_protocol_packages() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-berry-style.lock")
    assert pkgs is not None
    assert "react" in pkgs
    assert "react-dom" in pkgs
    assert "@types/node" in pkgs
    assert "@types/react" in pkgs
    assert "scheduler" in pkgs
    assert "loose-envify" in pkgs


def test_yarn_berry_skips_metadata_block() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-berry-style.lock")
    assert pkgs is not None
    assert "__metadata" not in pkgs


def test_yarn_berry_strips_npm_protocol_from_name() -> None:
    """Berry selectors look like `"react@npm:^18.2.0":` — the parser
    must yield `react`, NOT `react@npm` or `react@npm:^18.2.0`."""
    pkgs = parse_yarn_lock(FIXTURES / "yarn-berry-style.lock")
    assert pkgs is not None
    bad = [p for p in pkgs if "npm:" in p or "@npm" in p]
    assert bad == [], f"npm: protocol leaked: {bad}"


# --- counts roughly match expectation ------------------------------------


def test_pnpm_v6_fixture_yields_reasonable_count() -> None:
    """Sanity check on the fixture — should land between 5 and 50
    packages. If it goes outside that band, either the fixture is
    broken or the parser regressed."""
    pkgs = parse_pnpm_lock(FIXTURES / "pnpm-lock-react-style.yaml")
    assert pkgs is not None
    assert 5 <= len(pkgs) <= 50


def test_yarn_v1_fixture_yields_reasonable_count() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-v1-style.lock")
    assert pkgs is not None
    assert 5 <= len(pkgs) <= 50


def test_yarn_berry_fixture_yields_reasonable_count() -> None:
    pkgs = parse_yarn_lock(FIXTURES / "yarn-berry-style.lock")
    assert pkgs is not None
    assert 5 <= len(pkgs) <= 50
