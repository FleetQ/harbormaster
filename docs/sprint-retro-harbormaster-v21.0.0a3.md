# Sprint Retro — harbormaster v21.0.0a3

**Theme**: Empty-state polish across every dashboard surface + an
operator-tunable accent picker. The dashboard now uses one consistent
"headline + body + CTA" empty-state pattern everywhere, and operators
can dial in their own OKLCH accent from the inspector.

## What shipped

- **Empty-state polish** — six v8/v10/v19 one-liner stubs replaced with
  the canonical 3-part copy (headline + 1-2 sentence body + concrete
  CTA):
  - Dashboard Plugins card: `No entry points discovered.` →
    **No plugins installed.** + `pip install harbormaster-plugin-<name>` CTA.
  - Dashboard "Recent activity" card + inspector activity feed:
    plain `no recent calls` → **No recent activity.** + `ask_project` /
    `delegate_task` CTA.
  - Network page: terse `No MCP calls recorded yet — ask a project…` →
    **No MCP traffic yet.** + boxed body copy on a tinted surface.
  - Dispatcher trace page: two stubs (`No spans currently in flight`,
    `No completed traces yet`) → boxed cards with explicit `try
    ask_project from any client` and ring-buffer explanation.
  - Project detail Memories tab: `no memory files` → **No memory files
    yet.** + `+ new` and `serena init` CTAs.
  - Project detail Q&A History tab: tightened the v21.0.0a2 copy into
    the canonical pattern for visual consistency.
- **Operator-tunable accent picker** — new collapsible
  `<details data-inspector-accent>` block in the dashboard inspector
  with OKLCH hue (0-360°) and chroma (0-0.30) sliders, a live swatch,
  the rendered `oklch(…)` triplet, and Save / Reset buttons. Live
  preview without reload: the Alpine factory `accentPicker()` injects
  or mutates `<style id="hm-custom-accent">` in `<head>` on every
  slider event.
- **`UIConfig` pydantic model** — new `[ui]` config section with
  `accent_hue` (default `290.0`) and `accent_chroma` (default `0.22`).
  Defaults match the v19.0.0a4 Linear violet baseline byte-for-byte so
  the new section is a true no-op for existing installs. Validated by
  `_FORBID_EXTRA` so typos in operator configs surface as `ValidationError`.
- **`GET /api/settings/accent`** — returns the live `{hue, chroma}` so
  the picker hydrates from the on-disk config on first paint.
- **`PUT /api/settings/accent`** — writes `[ui] accent_hue` +
  `accent_chroma` to `~/.config/harbormaster/config.toml` atomically
  (tmpfile + rename), preserves any other top-level tables already in
  the file (e.g. `[server]`), validates ranges, and mutates the
  in-process `config.ui` so the next render of `base.html` SSR-emits
  the override block without a process restart.
- **SSR override** in `base.html` — when `[ui]` diverges from the
  violet baseline, a `<style id="hm-custom-accent">` block re-points
  `--color-accent-strong` / `--color-accent` (and the legacy `--hm-*`
  aliases) to the operator's hue/chroma so the page never flashes
  the default before the JS picker reapplies. Zero bytes overhead
  for the default-violet install (Jinja conditional gates emission).
- **`--color-foreground-dim` token** added to `tailwind.input.css`
  (dark + light + media-query blocks). One tier dimmer than
  `foreground-subtle` for empty-state body copy that sits on a tinted
  `bg-surface-2/40` card where we need a touch more lightness to keep
  WCAG AA contrast. Tailwind recompiled.
- **Docs** — added `[ui]` section to
  `docs/operator-config-reference.md` (TOC, key table with notes,
  worked example) so `test_every_config_field_documented` stays green.
- **Tests** — 17 new pins in `tests/ui/test_v21_empty_states_and_accent.py`:
  - Five template assertions per surface confirm the v8/v10 stubs are
    gone and the polished copy is present.
  - Two template assertions on the accent picker mount + base.html
    conditional override.
  - Eight backend assertions: GET defaults, GET configured values,
    PUT range validation (hue OOB, chroma OOB, negative hue, invalid
    payload), PUT TOML round-trip, and PUT preserves other top-level
    tables.
  - Two `UIConfig` model assertions: defaults match violet baseline +
    forbid-extra rejects typos.

## What we learned / re-confirmed

- **Hand-rolled TOML preservation pattern carries** — the
  `_write_accent_toml` helper is a near-mirror of
  `_write_project_budget_toml` from v21.0.0a2: read existing,
  mutate one section, hand-emit scalars then tables, atomic
  tmpfile+rename. No dependency on `tomli-w` for a 2-key table.
- **Live config mutation is the right shape for SSR overrides**.
  Rather than re-`load_config()` after PUT (which would have to
  invalidate cached state), we mutate `config.ui.*` in place — the
  exact same object that base.html's context comes from. Verified via
  the round-trip test (`PUT` → re-`GET` returns the new values without
  a restart).
- **Pre-existing test pattern collisions caught early**:
  - The a11y floor test flags any `<button>` lacking an accessible
    name. Initial Save/Reset markup had visible text but the auditor
    treats `text` as `ICON` when wrapped in `<span x-text>`. Added
    `aria-label` to both buttons.
  - `test_no_unhandled_async_click_handlers` flagged `async reset()`
    for missing try/catch. Wrapped the body so a backend failure
    during save() doesn't surface as an unhandled promise rejection.
  Both were fixed in the same commit — neither caused PR-level rework.
- **CDN Tailwind vs static build** — the dashboard pulls
  `cdn.tailwindcss.com` (JIT) AND the static `/static/tailwind.css`,
  which is the build hook output. CDN scans HTML for utility classes
  so the new `text-foreground-dim` works as soon as the token is in
  the cascade, but the static fallback needs a recompile via
  `npx @tailwindcss/cli` before the wheel ships. Did both.

## Test delta

- Before (clean main): 1650 passed, 44 failed, 16 errors (UI + unit
  suite, excluding the pre-broken screenshot harness).
- After: 1668 passed, 43 failed, 16 errors. **+18 new passing tests
  (17 new pins + 1 of the pre-existing failures is now passing),
  -1 net failure. No regressions.**

## Visual verification

Three screenshots captured against a verify-port instance
(`harbormaster-ui --port 17799`) without touching the operator UI on
17636:
- `/tmp/v21-a3-dashboard.png` — ACCENT COLOR collapsible visible in
  inspector; "No plugins installed." 3-part state visible in Plugins
  card; "No recent activity." 3-part state visible in Recent activity
  card.
- `/tmp/v21-a3-network-empty.png` — "No MCP traffic yet." boxed empty
  state with body copy explaining caller/target/timing/result.
- `/tmp/v21-a3-dispatcher-empty.png` — "No spans in flight." +
  "No completed traces yet." both rendered as polished boxed cards.

## Files touched

- `src/harbormaster/config.py` — new `UIConfig` model + wired into
  `HarbormasterConfig.ui`.
- `src/harbormaster/ui/routes.py` — `_user_config_toml_path` /
  `_write_accent_toml` helpers + `GET`/`PUT /api/settings/accent` +
  base.html render context (`ui_accent_hue`, `ui_accent_chroma`,
  `ui_accent_chroma_soft`).
- `src/harbormaster/ui/templates/base.html` — SSR conditional
  `<style id="hm-custom-accent">` override.
- `src/harbormaster/ui/templates/dashboard.html` — accent picker
  widget + `accentPicker()` factory + two polished empty states
  (Plugins, Recent activity, inspector activity).
- `src/harbormaster/ui/templates/network.html` — boxed empty state.
- `src/harbormaster/ui/templates/dispatcher_trace.html` — two boxed
  empty states.
- `src/harbormaster/ui/templates/project_detail.html` — two boxed
  empty states (Memories no files, Q&A history empty).
- `src/harbormaster/ui/static/tailwind.input.css` — new
  `--color-foreground-dim` token across `:root`, light, and dark
  blocks.
- `src/harbormaster/ui/static/tailwind.css` — recompiled output.
- `docs/operator-config-reference.md` — `[ui]` section (TOC + table +
  worked example).
- `tests/ui/test_v21_empty_states_and_accent.py` — 17 new test pins.

## Boundaries respected

- Operator UI on 17636 never killed; verify instance on 17799 only.
- No other phase's work touched; the accent picker is the single new
  surface, the empty-state polish is the single content-pass.
- Pre-existing test failures (browser-smoke flake, bridge test scope
  errors) left alone — those belong to whoever owns Playwright fixtures.
