# Sprint Retro — Harbormaster v3.0.0a6

**Date:** 2026-05-09
**Theme:** Made the UI usable on bearer-protected installs. Client-side
SSE / API fetches now carry the bearer token automatically.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `f181677` | feat(ui): bearer-token plumbing for SSE forms (v3.0.0a6) |

## Capabilities (this sprint)

### 1 · `<meta name="hm-auth-token">` + `window.hmFetch()`

Before: when `HARBORMASTER_UI_TOKEN` was set, the bearer middleware
401'd every same-origin fetch the dashboard made (ask form, fan-out,
recall, bridge status, plugins, projects). The dashboard rendered but
appeared broken — none of the live data populated.

After: when `auth_token` is passed into `create_app(...)`, base.html
emits a hidden `<meta name="hm-auth-token" content="...">`. A new
`window.hmFetch(url, init)` helper reads the meta and injects an
`Authorization: Bearer <token>` header on every call. When the meta
is absent (loopback + no env token), `hmFetch` falls through to
`fetch` unchanged.

Five templates converted from `fetch(` to `hmFetch(`:
`dashboard.html`, `project_detail.html`, `fan_out.html`,
`_partials/ask_form.html`, `_partials/delegate_form.html`.

### 2 · `_render()` helper auto-injects auth context

The token surface used to be a per-template concern, which would have
forced every new page to remember to include the meta tag. Instead,
a route-level `_render(request, template, extra)` helper merges the
auth context (and `version`) into every TemplateResponse:

```python
auth_ctx = {"auth_token": auth_token} if auth_token else {}

def _render(request, template, extra):
    ctx = {"version": __version__, **auth_ctx, **extra}
    return templates.TemplateResponse(request, template, ctx)
```

New pages added in v3.0.0a7+ will get the token plumbing for free.

### 3 · `harbormaster-ui` CLI plumbing

`cli.py` already resolves the token once via `_resolve_ui_token`. That
same value is now passed both to `build_bearer_middleware` *and* into
`create_app(auth_token=...)` — single source of truth, no env var
re-read inside routes.

## Real numbers

- 1/1 v3.0.0a5-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-ui-token-plumbing` directly via `--no-ff`
- 6 new unit tests (meta tag presence/absence, hmFetch routing across
  dashboard + fan_out + project_detail templates)
- Test suite delta: 605 + 1 skip → **611 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — all paths preserve plain-`fetch`
  semantics when no token is configured

## What worked

- **Single helper, no per-template context juggling.** The original
  cut had me passing `auth_token` to each TemplateResponse manually.
  The `_render()` helper made the change tighter and prevents future
  pages from silently dropping the meta tag.
- **`hmFetch` is the same name everywhere.** No "wrap fetch in
  feature-flag" forks of each form — every form converted from
  `fetch(` to `hmFetch(` with one find-and-replace pass.
- **JS-string-vs-meta-tag regression caught.** First test cut asserted
  on the literal string `"hm-auth-token"` not appearing — but the
  hmFetch helper itself contains the string as a JS literal. Fixed
  by asserting on the meta tag (`<meta name="hm-auth-token"`)
  specifically. Worth a retro callout because future tests asserting
  presence/absence of an HTML element should always anchor on the
  tag opening, not a string that may appear in scripts.

## What to change / next

- **Token is rendered into HTML.** Anyone with read access to a
  rendered page sees the bearer token. Acceptable trade-off because
  any reader of the page already passed bearer middleware (so they
  HAD the token), but a session-cookie path would be nicer for
  hostile-network setups. Defer — operator-only UI, low blast radius.
- **No CSRF protection.** Same reasoning: operator-only, single-user.
  Flag for v4 if multi-operator or third-party embedding ever happens.

## Action items for the next sprint (v3.0.0a7)

1. **Inline ask form on dashboard cards.** `_partials/ask_form.html`
   currently renders only on the project detail page. Move it to the
   dashboard's project grid (collapsible per card) so operators can
   ask without navigating. Reuse the partial directly; per-card Alpine
   `x-data` scope so card states don't collide.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
