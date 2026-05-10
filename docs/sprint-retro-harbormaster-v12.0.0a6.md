# Sprint Retro — Harbormaster v12.0.0a6

**Theme:** Cookie-backed bearer for SSE auth. Browser EventSource
cannot send custom headers, so SSE streams previously needed a
query-param token (less secure — token sat in URLs and access logs).
v12.0.0a6 introduces a cookie-backed alternative without breaking
the existing header path.

## What shipped

### Middleware (`src/harbormaster/transport.py`)

`BearerAuthMiddleware` now accepts EITHER:

  - `Authorization: Bearer <token>` header (existing — back-compat).
  - `hm-auth=<token>` cookie (NEW).

Decision tree:

  1. Header present + matches → 200.
  2. Header present + wrong → 401 (cookie NOT consulted).
  3. Header absent + cookie matches → 200.
  4. Header absent + cookie wrong → 401 ("invalid bearer cookie").
  5. Both absent → 401 ("missing Authorization header or hm-auth cookie").

The "header takes precedence over cookie" rule is deliberate — it
prevents an XSS-leaked cookie from being silently accepted while a
script forges a header. Errors keep the operator's diagnostics
specific.

Constant `HM_AUTH_COOKIE_NAME = "hm-auth"` exported for tests + the
endpoint to share one source of truth.

### `POST /api/auth/cookie` endpoint

Bridges header → cookie. Itself bearer-protected (no back door):

  - Reads `Authorization: Bearer <token>` from the request.
  - Returns `{"ok": true}` 200 with `Set-Cookie`:

      hm-auth=<token>; HttpOnly; SameSite=Strict; Max-Age=43200;
      Path=/; Secure (when scheme is https)

  - Idempotent: when called with cookie-only (no header) it re-sets
    the same cookie, refreshing the 12h Max-Age window.

Cookie attribute rationale:

  - **HttpOnly** — JavaScript can't read it, so an XSS payload can't
    exfiltrate the token.
  - **SameSite=Strict** — never sent on cross-origin requests, so a
    third-party attacker site can't trigger authenticated requests.
  - **Secure** (https-only) — set automatically when the request
    came in over https. Loopback http (the dev path) gets the cookie
    without `Secure` so the test harness works.
  - **Max-Age=43200 (12h)** — long enough for a working day,
    short enough that an unattended laptop doesn't grant indefinite
    access. Re-prime call refreshes it.
  - **Path=/** — every UI endpoint sees the cookie.

### Dashboard primer (`templates/base.html`)

`primeAuthCookie()` IIFE fires `POST /api/auth/cookie` on page load
when the `<meta name="hm-auth-token">` element is present. Fire-
and-forget: a network blip on prime doesn't break the page —
`hmFetch` still carries the bearer header on every fetch call. SSE
streams will simply 401 until the prime call eventually succeeds.

No-op on loopback unauth UI (no meta → early return).

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1281   | 1293  |
| New (`tests/ui/test_cookie_auth.py`)       | —      |   +12 |

Coverage:

- Middleware decision matrix:
  - Cookie-only with right token → 200.
  - Cookie with wrong token → 401 ("invalid bearer cookie").
  - Header takes precedence: wrong header + correct cookie → 401
    ("invalid bearer token").
  - No header, no cookie → 401 ("missing Authorization header or
    hm-auth cookie").
  - Header-only (back-compat) still works.
- Endpoint:
  - Valid bearer header sets the cookie; response includes it.
  - Set-Cookie carries HttpOnly + SameSite=Strict + Max-Age=43200
    + Path=/.
  - Endpoint without auth → 401 (not a back door).
  - Cookie-only re-prime works (refreshes Max-Age).
  - Full loop: prime via header, then cookie-only request 200s.
- Primer:
  - `/` with auth_token has `primeAuthCookie` + `/api/auth/cookie`
    + `credentials: 'same-origin'` + fire-and-forget `.catch`.
  - `/` without auth_token still has the function defined (early-
    return path) and no `<meta name="hm-auth-token">`.

The existing `tests/unit/test_transport.py` continues to pass — all
header-only test cases remain green.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1293 passed, 2 skipped in 39.97s
```

## Architecture notes

- **Why not just use the cookie everywhere?** Two reasons:
  (a) Non-browser HTTP clients (FleetQ bridge, curl, smoke tests)
  use the header path. Forcing them to acquire a cookie would
  require a stateful flow that doesn't fit a stateless MCP API.
  (b) The header path is one fewer round trip on first connect.
- **Why not just use the cookie for SSE only?** That's a per-route
  carve-out. The middleware is global; doing per-route auth would
  duplicate the policy. Accepting both shapes globally is simpler
  and the precedence rule keeps the security story intact.
- **Why HttpOnly + 12h Max-Age?** Defence-in-depth. Even if an XSS
  payload landed, it can't read the cookie (HttpOnly) or persist
  beyond 12 hours unattended.
- **Why fire-and-forget primer?** The page is usable WITHOUT the
  cookie — `hmFetch` carries the header on every API call. The
  cookie ONLY matters for SSE. So a primer failure degrades to "SSE
  doesn't work yet" instead of "page is broken". Once the network
  comes back the primer fires on the next page load.
- **Why re-prime on cookie-only?** Without it, an operator's 12h
  session would always have a hard stop. A simple "every page load
  refreshes the cookie" rule turns the limit into "max 12h of
  inactivity" — much friendlier.

## Deviations

None. Phase scope matched plan exactly. The feature was authorised
for an `a<N>.5` split; not needed — the API surface and tests came
together cleanly.

## Next

Phase 7 — light-mode toggle (last alpha before GA).
