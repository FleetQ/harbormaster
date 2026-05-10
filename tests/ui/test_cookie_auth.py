"""v12.0.0a6: cookie-backed bearer for SSE auth.

Browsers can't send custom headers on EventSource connections, so SSE
streams previously needed a query-param token (less secure — token
sat in URLs and access logs). v12.0.0a6:

  - Middleware accepts EITHER `Authorization: Bearer ...` header OR
    `hm-auth` cookie carrying the same token.
  - New endpoint POST /api/auth/cookie sets the cookie when called
    with a valid Bearer header. HttpOnly + SameSite=Strict + Secure
    (https) + Max-Age=12h.
  - Dashboard primes the cookie on page load (fire-and-forget) so
    subsequent SSE connects work without query-param plumbing.

Test matrix:
  - Header-only auth still works (back-compat).
  - Cookie-only auth works (the new path).
  - Both present + agree → 200.
  - Wrong header → 401 (cookie not consulted as fallback).
  - Wrong cookie + missing header → 401.
  - No header, no cookie → 401.
  - POST /api/auth/cookie sets the cookie with the right attrs.
  - Re-POST with cookie-only refreshes the Max-Age.
"""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.transport import HM_AUTH_COOKIE_NAME, build_bearer_middleware
from harbormaster.ui import create_app


def _make_starlette_app(token: str):  # noqa: ANN202 - test helper
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def hello(request):  # noqa: ANN202 - starlette handler
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", hello)])
    app.add_middleware(build_bearer_middleware(token))
    return app


# -- middleware: cookie path ------------------------------------------


def test_middleware_accepts_hm_auth_cookie() -> None:
    client = TestClient(_make_starlette_app("secret"))
    r = client.get("/", cookies={HM_AUTH_COOKIE_NAME: "secret"})
    assert r.status_code == 200
    assert r.text == "ok"


def test_middleware_rejects_wrong_cookie() -> None:
    client = TestClient(_make_starlette_app("secret"))
    r = client.get("/", cookies={HM_AUTH_COOKIE_NAME: "wrong"})
    assert r.status_code == 401
    assert "invalid bearer cookie" in r.text


def test_middleware_rejects_no_header_no_cookie() -> None:
    client = TestClient(_make_starlette_app("secret"))
    r = client.get("/")
    assert r.status_code == 401
    assert "missing" in r.text.lower()


def test_middleware_header_takes_precedence_over_cookie() -> None:
    """Header is checked first; a wrong header 401s even if a valid
    cookie is present. This prevents an XSS-leaked cookie from being
    silently accepted while a script tries to forge a header."""
    client = TestClient(_make_starlette_app("secret"))
    r = client.get(
        "/",
        headers={"Authorization": "Bearer wrong"},
        cookies={HM_AUTH_COOKIE_NAME: "secret"},
    )
    assert r.status_code == 401
    assert "invalid bearer token" in r.text


def test_middleware_correct_header_still_works() -> None:
    """Back-compat: header-only auth path is unchanged."""
    client = TestClient(_make_starlette_app("secret"))
    r = client.get("/", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200


# -- POST /api/auth/cookie endpoint -----------------------------------


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


def _ui_client_with_token(tmp_path: Path, token: str) -> TestClient:
    app = create_app(_config(tmp_path), auth_token=token)
    app.add_middleware(build_bearer_middleware(token))
    return TestClient(app)


def test_set_auth_cookie_endpoint_returns_200_with_bearer(tmp_path: Path) -> None:
    client = _ui_client_with_token(tmp_path, "secret")
    r = client.post(
        "/api/auth/cookie",
        headers={"Authorization": "Bearer secret"},
    )
    assert r.status_code == 200
    assert HM_AUTH_COOKIE_NAME in r.cookies
    assert r.cookies[HM_AUTH_COOKIE_NAME] == "secret"


def test_set_auth_cookie_sets_httponly_and_samesite_strict(tmp_path: Path) -> None:
    """Cookie security attributes are mandatory:
    - HttpOnly: not readable from JS (XSS defence).
    - SameSite=Strict: never sent cross-origin (CSRF defence).
    - Secure is set only when https; loopback http test gets it omitted.
    """
    client = _ui_client_with_token(tmp_path, "secret")
    r = client.post(
        "/api/auth/cookie",
        headers={"Authorization": "Bearer secret"},
    )
    set_cookie = r.headers.get("set-cookie", "")
    assert HM_AUTH_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    # SameSite is case-sensitive in headers but tools render it
    # capitalised; check both spellings for robustness.
    assert "samesite=strict" in set_cookie.lower()
    assert "max-age=43200" in set_cookie.lower()  # 12 * 3600
    assert "path=/" in set_cookie.lower()


def test_set_auth_cookie_endpoint_protected_by_middleware(tmp_path: Path) -> None:
    """Without auth the endpoint 401s — it's not a back door."""
    client = _ui_client_with_token(tmp_path, "secret")
    r = client.post("/api/auth/cookie")
    assert r.status_code == 401


def test_set_auth_cookie_endpoint_works_via_existing_cookie(tmp_path: Path) -> None:
    """Once the cookie exists, calling the endpoint again refreshes
    the Max-Age window without needing the header."""
    client = _ui_client_with_token(tmp_path, "secret")
    r = client.post(
        "/api/auth/cookie",
        cookies={HM_AUTH_COOKIE_NAME: "secret"},
    )
    assert r.status_code == 200
    assert HM_AUTH_COOKIE_NAME in r.cookies


def test_full_loop_sse_works_with_cookie_only(tmp_path: Path) -> None:
    """The integration smoke: prime the cookie via POST, then hit a
    bearer-protected endpoint with cookie ONLY (no header). Should 200."""
    client = _ui_client_with_token(tmp_path, "secret")
    # Prime the cookie via header (TestClient stores it in the jar).
    prime = client.post(
        "/api/auth/cookie",
        headers={"Authorization": "Bearer secret"},
    )
    assert prime.status_code == 200
    # Now hit any other endpoint without the header — TestClient
    # automatically sends the cookie from its jar.
    r = client.get("/api/health")
    assert r.status_code == 200


# -- base.html primer -------------------------------------------------


def test_base_html_primes_cookie_on_load(tmp_path: Path) -> None:
    """The dashboard fires POST /api/auth/cookie on load when the
    auth_token meta is present, so SSE streams (which can't carry
    headers) work via the cookie thereafter."""
    client = _ui_client_with_token(tmp_path, "secret")
    body = client.get(
        "/", headers={"Authorization": "Bearer secret"},
    ).text
    assert "primeAuthCookie" in body
    assert "/api/auth/cookie" in body
    assert "credentials: 'same-origin'" in body
    # Fire-and-forget: no await / .then chain that could block render.
    assert ".catch(function" in body


def test_base_html_skips_primer_when_no_token(tmp_path: Path) -> None:
    """Loopback unauth UI (no auth_token rendered) → no primer fires.
    The primer guards on the meta element existing, so the function
    body is present in HTML but the no-op path triggers."""
    client = TestClient(create_app(_config(tmp_path)))  # auth_token=None
    body = client.get("/").text
    # Function still defined (it's a static helper), but the meta is
    # absent so the early-return path runs.
    assert "primeAuthCookie" in body
    assert 'meta name="hm-auth-token"' not in body
