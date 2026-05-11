"""HTTP transport bring-up — bearer-token auth + uvicorn runner.

stdio transport is process-bound (whoever spawns the MCP server owns it),
so no auth is needed there. SSE / streamable-http expose an HTTP surface
that any reachable client can hit, so v1.0 enforces a required bearer
token on those transports — there is no opt-out.

Token comes from an environment variable (default `HARBORMASTER_MCP_TOKEN`,
overridable via `--auth-token-env`). If the env var is empty when an HTTP
transport is requested, the entry point exits 2 with a recipe for setting
it instead of binding an unauthenticated port.

`Authorization: Bearer <token>` is the only accepted form. Any other shape
(missing header, wrong prefix, wrong value) returns 401 Unauthorized.
"""
from __future__ import annotations

import hmac
import os
import sys
from typing import Any


def resolve_auth_token(env_var: str, transport: str) -> str:
    """Return the bearer token from env, or '' for stdio (which doesn't need auth)."""
    if transport == "stdio":
        return ""
    return os.environ.get(env_var, "").strip()


def require_auth_token_or_exit(env_var: str, transport: str) -> str:
    """Same as resolve_auth_token but exits 2 with a usage hint if empty.

    Use at the entry point so HTTP transports never bind without a token.
    """
    if transport == "stdio":
        return ""
    token = os.environ.get(env_var, "").strip()
    if not token:
        print(
            f"Error: --transport {transport} requires a bearer token.\n"
            f"Set ${env_var} to a strong secret, then re-run. Example:\n"
            f"  export {env_var}="
            f"$(python -c 'import secrets; print(secrets.token_urlsafe(32))')\n"
            f"v1.0 has no auth-disabled HTTP mode — use --transport stdio "
            f"for local-only no-auth use.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return token


HM_AUTH_COOKIE_NAME = "hm-auth"


def build_bearer_middleware(expected_token: str) -> Any:
    """Return a Starlette BaseHTTPMiddleware subclass enforcing bearer auth.

    Accepted auth shapes (v12.0.0a6 — cookie path added):
      - `Authorization: Bearer <token>` header (existing — works for
        every HTTP client + the dashboard's hmFetch helper).
      - `hm-auth` cookie carrying the same token (NEW — required for
        browser EventSource which can't set headers; previously the
        dashboard depended on a query-param token, less secure).

    Returned class is curried with the expected token, so callers do:
        app.add_middleware(build_bearer_middleware(token))

    Imports starlette lazily — the [ui] / HTTP-transport code path is the
    only thing that needs starlette installed; stdio users shouldn't be
    forced to install it.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    expected_header = f"Bearer {expected_token}"

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            authz = request.headers.get("Authorization", "")
            if authz:
                # hmac.compare_digest = constant-time comparison; defeats
                # the timing-side-channel attack on byte-by-byte `!=`.
                if not hmac.compare_digest(authz, expected_header):
                    return Response(
                        "invalid bearer token", status_code=401,
                    )
                return await call_next(request)
            # v12.0.0a6: cookie fallback for browser EventSource which
            # cannot send custom headers. The cookie value carries the
            # raw token (no "Bearer " prefix).
            cookie_token = request.cookies.get(HM_AUTH_COOKIE_NAME, "")
            if cookie_token:
                if not hmac.compare_digest(cookie_token, expected_token):
                    return Response(
                        "invalid bearer cookie", status_code=401,
                    )
                return await call_next(request)
            return Response(
                "missing Authorization header or hm-auth cookie",
                status_code=401,
            )

    return BearerAuthMiddleware


def run_http_transport(
    mcp: Any,
    *,
    transport: str,
    host: str,
    port: int,
    token: str,
) -> None:
    """Bring up an HTTP-based MCP transport with bearer-token auth.

    Wraps FastMCP's underlying Starlette app with a 401-on-missing-or-wrong
    middleware, then runs uvicorn. Caller is responsible for having a valid
    non-empty `token` (use `require_auth_token_or_exit` upstream).
    """
    import uvicorn

    if transport == "sse":
        app = mcp.sse_app()
    elif transport == "streamable-http":
        app = mcp.streamable_http_app()
    else:
        raise ValueError(f"unknown transport: {transport!r}")

    app.add_middleware(build_bearer_middleware(token))
    uvicorn.run(app, host=host, port=port, log_config=None)
