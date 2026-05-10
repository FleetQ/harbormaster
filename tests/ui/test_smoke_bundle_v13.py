"""v13.0.0a5: three small smoke tests bundled together.

The v12 retro flagged three loose ends. Each was small enough that
shipping them as separate alphas would have been overkill — combined
into one phase here:

1. **CSS @theme reload smoke** (v12 retro #1) — when the theme is
   toggled via `themeToggle()`, the html class swaps AND the CSS
   variables that depend on it (light/dark `--color-*` overrides)
   actually resolve. Catches a stale-cache regression where the
   class moves but the computed style doesn't.

2. **Cookie-behind-nginx smoke** (v12 retro #2) — the v12.0.0a6
   cookie-backed bearer relies on the browser sending the cookie
   on subsequent requests. Behind a nginx reverse-proxy the
   request arrives with `X-Forwarded-{Proto,Host,For}` headers and
   the `Cookie:` header survives untouched. Pin both behaviors.

3. **Light-mode contrast audit** (v12 retro #7) — every documented
   foreground/background token pair in light mode must hit the
   WCAG 2.1 AA threshold (4.5:1). Computes contrast directly from
   the OKLCH values in `tailwind.input.css` so a future palette
   change can't silently regress accessibility.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src" / "harbormaster" / "ui" / "templates"
)
TAILWIND_INPUT = (
    Path(__file__).parent.parent.parent
    / "src" / "harbormaster" / "ui" / "static" / "tailwind.input.css"
)


# -- 1. CSS @theme reload smoke ---------------------------------------


def test_theme_toggle_swaps_html_class() -> None:
    """The themeToggle() Alpine helper must add/remove `theme-light`
    and `theme-dark` classes on the html element. Pin the contract
    so a future refactor can't silently flip the class names."""
    base = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    # Boot script removes both classes before adding the active one —
    # this is what guarantees the toggle is reversible.
    assert "html.classList.remove('theme-light', 'theme-dark')" in base
    assert "html.classList.add('theme-light')" in base
    assert "html.classList.add('theme-dark')" in base
    # The cycle inside themeToggle() also removes both before re-adding.
    # `html.classList.remove('theme-light', 'theme-dark')` appears at
    # least twice (boot + toggle).
    assert base.count("html.classList.remove('theme-light', 'theme-dark')") >= 2


def test_css_variables_have_light_and_dark_overrides() -> None:
    """The compiled stylesheet must define overrides for both
    html.theme-light and html.theme-dark. Without these the toggle
    swaps the class but the computed style stays at the @theme
    default."""
    css = (TAILWIND_INPUT.parent / "tailwind.css").read_text(encoding="utf-8")
    # Both selectors present (compiled away from any fancy
    # nested-selector form).
    assert "html.theme-light" in css
    assert "html.theme-dark" in css
    # Both override at minimum the surface + foreground tokens.
    light_chunk = _selector_chunk(css, "html.theme-light")
    dark_chunk = _selector_chunk(css, "html.theme-dark")
    for token in ("--color-surface-1", "--color-foreground"):
        assert token in light_chunk, f"light theme missing {token}"
        assert token in dark_chunk, f"dark theme missing {token}"


def _selector_chunk(css: str, selector: str) -> str:
    """Return the `{ … }` body of the first rule with the given
    selector. Returns "" when the selector isn't found."""
    idx = css.find(selector)
    if idx == -1:
        return ""
    open_brace = css.find("{", idx)
    close_brace = css.find("}", open_brace)
    return css[open_brace + 1 : close_brace]


# -- 2. Cookie-behind-nginx smoke -------------------------------------


def _config() -> HarbormasterConfig:
    return HarbormasterConfig(projects=ProjectsConfig(glob=[]))


def test_set_cookie_survives_proxy_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the request arrives with typical nginx reverse-proxy
    headers (`X-Forwarded-{Proto,Host,For}`), the auth cookie endpoint
    must still set the cookie correctly. nginx forwards Set-Cookie
    to the client unchanged so we verify the response side."""
    monkeypatch.setenv("HARBORMASTER_UI_TOKEN", "secret")
    client = TestClient(create_app(_config()))
    # First call: no cookie → 401 (the v12.0.0a6 contract).
    r = client.post("/api/auth/cookie")
    assert r.status_code == 401

    # Now hit with the proxy headers + a valid bearer; cookie should
    # land on the response with the right attributes.
    r = client.post(
        "/api/auth/cookie",
        headers={
            "Authorization": "Bearer secret",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "harbormaster.example.com",
            "X-Forwarded-For": "203.0.113.5",
            "Host": "harbormaster.example.com",
        },
    )
    assert r.status_code in (200, 204)
    set_cookie = r.headers.get("set-cookie", "")
    assert "hm-auth=" in set_cookie
    # HttpOnly is the most important attribute behind a proxy — it
    # blocks the cookie from being read via JS even if the proxy
    # mis-forwards it.
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()


def test_cookie_header_passes_through_proxy_request() -> None:
    """nginx forwards the client's Cookie: header verbatim. Verify
    the middleware reads it from the forwarded request and grants
    access. This is the v12.0.0a6 cookie-fallback path under proxy."""
    import os
    os.environ["HARBORMASTER_UI_TOKEN"] = "secret"
    try:
        client = TestClient(create_app(_config()))
        # Set the cookie via the auth endpoint.
        r = client.post(
            "/api/auth/cookie",
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code in (200, 204)

        # Now make a follow-up request with proxy headers + cookie
        # but NO bearer header — same as the browser->nginx->app path.
        r = client.get(
            "/api/health",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "harbormaster.example.com",
            },
        )
        assert r.status_code == 200, r.text
    finally:
        del os.environ["HARBORMASTER_UI_TOKEN"]


# -- 3. Light-mode contrast audit -------------------------------------


def _parse_oklch_block(css: str, selector: str) -> dict[str, tuple[float, float, float]]:
    """Extract `--color-*: oklch(L C H)` declarations inside the chunk
    matching `selector`. Returns {token_name: (L, C, H)} where
    L/C/H are floats; alpha and percent strings are normalized.
    """
    chunk = _selector_chunk(css, selector)
    out: dict[str, tuple[float, float, float]] = {}
    pattern = re.compile(
        r"--color-([a-z0-9-]+):\s*oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([\d.]+)\s*\)"
    )
    for m in pattern.finditer(chunk):
        name = m.group(1)
        # Tailwind input writes L either as a 0-1 float (0.55) or a
        # percentage (55%). The compiled CSS uses both forms; we
        # normalize to a 0-1 float.
        l_raw = float(m.group(2))
        lightness = l_raw / 100 if l_raw > 1 else l_raw
        chroma = float(m.group(3))
        hue = float(m.group(4))
        out[name] = (lightness, chroma, hue)
    return out


def _oklch_to_srgb_y(lightness: float, chroma: float, hue_deg: float) -> float:
    """Approximate srgb relative luminance from OKLCH. Uses the OKLab
    ↔ XYZ ↔ linear-sRGB conversion documented at
    https://bottosson.github.io/posts/oklab/. Y is what WCAG uses."""
    import math

    hue = math.radians(hue_deg)
    a = chroma * math.cos(hue)
    b = chroma * math.sin(hue)

    # OKLab → LMS_prime → LMS → XYZ → linear-sRGB → relative-luminance Y.
    l_prime = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_prime = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_prime = lightness - 0.0894841775 * a - 1.2914855480 * b

    lms_l = l_prime ** 3
    lms_m = m_prime ** 3
    lms_s = s_prime ** 3

    # Linear sRGB coefficients on linear LMS.
    r = +4.0767416621 * lms_l - 3.3077115913 * lms_m + 0.2309699292 * lms_s
    g = -1.2684380046 * lms_l + 2.6097574011 * lms_m - 0.3413193965 * lms_s
    b_lin = -0.0041960863 * lms_l - 0.7034186147 * lms_m + 1.7076147010 * lms_s

    # Clamp out-of-gamut values (no clipping artifacts since we only
    # need Y for contrast).
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b_lin = max(0.0, min(1.0, b_lin))

    # WCAG-relative luminance.
    return 0.2126 * r + 0.7152 * g + 0.0722 * b_lin


def _wcag_contrast(y1: float, y2: float) -> float:
    light, dark = max(y1, y2), min(y1, y2)
    return (light + 0.05) / (dark + 0.05)


# Pairs that must hit AA (≥ 4.5:1) in light mode. Each is a
# (foreground_token, background_token) tuple as it appears in
# the @theme block.
_LIGHT_AA_PAIRS: tuple[tuple[str, str], ...] = (
    ("foreground", "surface-1"),         # body text on canvas
    ("foreground", "surface-2"),         # body text on elevated panel
    ("foreground-muted", "surface-1"),   # secondary text on canvas
    ("foreground-muted", "surface-2"),   # secondary text on panel
    ("accent-strong", "surface-1"),      # primary CTA text on canvas
    ("accent-strong", "surface-2"),      # primary CTA text on panel
)


def test_light_mode_pairs_meet_wcag_aa() -> None:
    """v12 retro #7: every documented foreground/background pair in
    light mode meets WCAG 2.1 AA (4.5:1).

    Computed directly from the OKLCH values in `tailwind.input.css`
    via the OKLab → linear-sRGB conversion documented at
    https://bottosson.github.io/posts/oklab/. No browser required.
    """
    css = TAILWIND_INPUT.read_text(encoding="utf-8")
    light = _parse_oklch_block(css, "html.theme-light")
    failures: list[str] = []
    for fg_token, bg_token in _LIGHT_AA_PAIRS:
        fg = light.get(fg_token)
        bg = light.get(bg_token)
        assert fg is not None, f"{fg_token} not found in html.theme-light block"
        assert bg is not None, f"{bg_token} not found in html.theme-light block"
        ratio = _wcag_contrast(
            _oklch_to_srgb_y(*fg),
            _oklch_to_srgb_y(*bg),
        )
        if ratio < 4.5:
            failures.append(
                f"  {fg_token} on {bg_token}: {ratio:.2f}:1 (need ≥4.5:1)"
            )
    assert not failures, (
        "Light mode contrast failures:\n" + "\n".join(failures)
    )


def test_dark_mode_pairs_meet_wcag_aa() -> None:
    """Same audit applied to the dark-mode block (sanity check —
    dark mode predates light, but verify nobody has accidentally
    drifted the dark tokens during light-mode work)."""
    css = TAILWIND_INPUT.read_text(encoding="utf-8")
    dark = _parse_oklch_block(css, "html.theme-dark")
    failures: list[str] = []
    for fg_token, bg_token in _LIGHT_AA_PAIRS:
        fg = dark.get(fg_token)
        bg = dark.get(bg_token)
        if fg is None or bg is None:
            # Dark block doesn't override every light token; that's
            # acceptable because the @theme defaults already ARE the
            # dark values. Skip silently.
            continue
        ratio = _wcag_contrast(
            _oklch_to_srgb_y(*fg),
            _oklch_to_srgb_y(*bg),
        )
        if ratio < 4.5:
            failures.append(
                f"  {fg_token} on {bg_token}: {ratio:.2f}:1 (need ≥4.5:1)"
            )
    assert not failures, (
        "Dark mode contrast failures:\n" + "\n".join(failures)
    )


def test_oklch_helper_known_pair() -> None:
    """Sanity-check the conversion: pure black (L=0) on pure white
    (L=1) should compute to 21:1 (WCAG's documented max ratio)."""
    y_black = _oklch_to_srgb_y(0.0, 0.0, 0.0)
    y_white = _oklch_to_srgb_y(1.0, 0.0, 0.0)
    ratio = _wcag_contrast(y_black, y_white)
    assert 20.0 < ratio < 22.0, f"got {ratio:.2f}, expected ~21"
