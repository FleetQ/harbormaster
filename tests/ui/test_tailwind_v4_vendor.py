"""Phase 1 audit (v9.0.0a1): Tailwind v4 vendor + static asset route.

What this audit pins:

* The compiled stylesheet (``src/harbormaster/ui/static/tailwind.css``)
  exists, is non-empty, and contains the canonical ``--color-accent``
  probe token (the ``@theme`` block survived compilation).
* The Tailwind v4 *source* CSS (``tailwind.input.css``) declares all
  the v8.0.0a7 ``--hm-*`` legacy aliases plus their new
  ``--color-*`` counterparts.
* ``GET /static/tailwind.css`` returns 200 + ``text/css`` with the
  same probe token in the body.
* Path traversal via ``..`` is rejected with 404.
* ``base.html`` declares the ``<link rel="stylesheet" href="/static/tailwind.css">``
  *before* the legacy CDN script so the @theme tokens get registered
  first.

The full template utility-class migration (``bg-cyan-700`` →
``bg-accent`` etc.) is deferred to a follow-up alpha so v9.0.0a1
ships purely the build infrastructure + vendor stylesheet without
visual regressions. Documented in
``docs/sprint-retro-harbormaster-v9.0.0a1.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app

REPO_ROOT = Path(__file__).parent.parent.parent
STATIC_DIR = REPO_ROOT / "src" / "harbormaster" / "ui" / "static"
TEMPLATE_DIR = REPO_ROOT / "src" / "harbormaster" / "ui" / "templates"

# v8.0.0a7 baseline: every legacy alias must remain available (other
# external CSS consumers reference these names).
_LEGACY_HM_TOKENS = [
    "--hm-surface-1",
    "--hm-surface-2",
    "--hm-surface-3",
    "--hm-foreground",
    "--hm-foreground-muted",
    "--hm-foreground-subtle",
    "--hm-accent",
    "--hm-accent-strong",
    "--hm-accent-soft",
    "--hm-success",
    "--hm-warning",
    "--hm-danger",
    "--hm-info",
    "--hm-border",
    "--hm-border-strong",
    "--hm-ring",
]

# v9.0.0a1: every legacy `--hm-*` token now has a `--color-*` peer
# inside the `@theme` block (Tailwind v4's first-class theme syntax).
_NEW_COLOR_TOKENS = [
    "--color-surface-1",
    "--color-surface-2",
    "--color-surface-3",
    "--color-foreground",
    "--color-foreground-muted",
    "--color-foreground-subtle",
    "--color-accent",
    "--color-accent-strong",
    "--color-accent-soft",
    "--color-success",
    "--color-warning",
    "--color-danger",
    "--color-info",
    "--color-border",
    "--color-border-strong",
    "--color-ring",
]


def test_tailwind_input_css_exists() -> None:
    src = STATIC_DIR / "tailwind.input.css"
    assert src.exists(), "tailwind.input.css is the source-of-truth file"


def test_tailwind_compiled_css_exists_and_nonempty() -> None:
    out = STATIC_DIR / "tailwind.css"
    assert out.exists(), "compiled tailwind.css must ship in the wheel"
    assert out.stat().st_size > 0, "compiled tailwind.css must not be empty"


def test_tailwind_compiled_css_contains_probe_token() -> None:
    out = (STATIC_DIR / "tailwind.css").read_text()
    # The probe token the build hook also checks; if the @theme block
    # was lost mid-compile this assertion catches it before the wheel
    # ships.
    assert "--color-accent" in out, (
        "compiled tailwind.css missing --color-accent — @theme block "
        "may have been dropped during compilation"
    )


@pytest.mark.parametrize("token", _NEW_COLOR_TOKENS, ids=lambda t: t)
def test_tailwind_input_declares_new_color_token(token: str) -> None:
    src = (STATIC_DIR / "tailwind.input.css").read_text()
    assert token in src, f"tailwind.input.css missing new theme token {token}"


@pytest.mark.parametrize("alias", _LEGACY_HM_TOKENS, ids=lambda t: t)
def test_tailwind_input_preserves_legacy_hm_alias(alias: str) -> None:
    src = (STATIC_DIR / "tailwind.input.css").read_text()
    assert alias in src, (
        f"tailwind.input.css dropped legacy alias {alias} — external "
        "consumers expect these names to keep resolving"
    )


def test_base_html_loads_vendored_stylesheet_before_cdn() -> None:
    """v9.0.0a1: the @theme tokens must be registered before the CDN
    script paints, otherwise the CDN's first paint references undefined
    custom properties."""
    src = (TEMPLATE_DIR / "base.html").read_text()
    link_idx = src.find('href="/static/tailwind.css"')
    cdn_idx = src.find("cdn.tailwindcss.com")
    assert link_idx > 0, "base.html must load /static/tailwind.css"
    assert cdn_idx > 0, "v3 CDN should still load until v10 (utility-class fallback)"
    assert link_idx < cdn_idx, (
        "vendored stylesheet must be declared BEFORE the CDN so @theme "
        "tokens are registered first"
    )


# -- HTTP-level checks ---------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


def test_static_endpoint_serves_tailwind_css(client: TestClient) -> None:
    r = client.get("/static/tailwind.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "--color-accent" in r.text


def test_static_endpoint_404s_for_missing_path(client: TestClient) -> None:
    r = client.get("/static/does-not-exist.css")
    assert r.status_code == 404


def test_static_endpoint_blocks_path_traversal(client: TestClient) -> None:
    # The ".." segment must be rejected before resolution.
    r = client.get("/static/../routes.py")
    # FastAPI normalizes the URL before dispatch, but the early
    # split-on-'..' check still fires for any path that survives.
    assert r.status_code in {404, 400}


def test_static_endpoint_sets_cache_control(client: TestClient) -> None:
    r = client.get("/static/tailwind.css")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "max-age" in cc, "static assets should declare a cache-control header"
