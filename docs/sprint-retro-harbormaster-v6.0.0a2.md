# Sprint Retro — Harbormaster v6.0.0a2

**Date:** 2026-05-09
**Theme:** Three-tier optimistic visual + operator-tunable threshold.
v5.0.0a4's binary "fresh / stale" became "fresh / writing back / stuck".

## What landed

| SHA | Subject |
|-----|---------|
| `d78cee1` | feat(ui): optimistic escalation tier + configurable threshold |

## Capabilities

### 1 · `[history] optimistic_stale_seconds` config

```toml
[history]
optimistic_stale_seconds = 10   # default 5; range 1..600
```

Operators on slow networks (or running locally with a sluggish disk)
can bump this without recompiling. Range-validated by Pydantic.

### 2 · Three-tier escalation

| Age | Tier | Visual |
|-----|------|--------|
| `0..N` | `fresh` | cyan border + "● new" badge |
| `N..(N×6)` | `stale` | cyan border + amber spinner ("writing back…") |
| `> N×6` | `stuck` | rose border + "⚠ stuck?" badge |

With default `N=5`: fresh ≤5s, stale 5-30s, stuck >30s.

The escalation is purely visual — the server's reconciliation flow
still runs unchanged. The tier just tells the operator how worried
to be.

### 3 · Wire shape: meta tag

```html
<meta name="hm-optimistic-stale-seconds" content="5">
```

Plumbed through `base.html` from `_render(ctx={..., optimistic_stale_seconds: ...})`.
JS `_staleThreshold()` reads it once with a sane fallback (5) when
the tag is absent.

## Real numbers

- 1/1 v6.0.0a1-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 7 new tests (meta-tag emission, tier strings, threshold logic,
  config default + range validation)
- Test suite delta: 710 + 2 skips → **717 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean
- 0 backwards-incompatible changes — additive config + UI tier

## What worked

- **Same plumbing pattern as auth_token (v3.0.0a6).** Config →
  `_render` ctx → base.html `<meta>` → JS reader. New surfaces
  inherit the pattern for free.
- **`tier()` returns a string, not a boolean.** Three values
  ("fresh"/"stale"/"stuck") are easier to reason about than two
  booleans (isStale, isStuck). The `x-show` bindings are direct
  equality checks; no compound conditions in the template.
- **`isStale` kept for back-compat.** v5.0.0a4 callers (if any
  outside the repo) keep working — `isStale` is now a thin wrapper
  that returns true for both stale + stuck tiers.
- **`6×` ratio for stuck threshold.** Not arbitrary — it gives
  fresh:stale:stuck a 1:5:∞ time budget. With default 5s, stuck
  hits at 30s, which matches the bridge-state stale-after-30s
  threshold (v3.0.0a2). Operators have one mental clock.

## What to change / next

- **No "retry stuck writeback" affordance.** When an entry sits in
  `stuck` tier the operator just sees the badge — no button to
  manually re-trigger writeback. Acceptable: the underlying
  retry/reconcile is still happening; the badge is informational.
  Defer.
- **Threshold is global per-install, not per-host.** A slow remote
  host might warrant a higher threshold than local. Defer until
  observed.

## Action items for the next sprint (v6.0.0a3)

1. **Dashboard sort + group controls.** v5.0.0a6 filter narrows;
   v6.0.0a3 also organises. Sort dropdown (last_commit / alpha /
   language). Group toggle (flat / by language). URL state alongside
   the existing filter param.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.
- Per-host stale thresholds — defer until observed.
- "Retry stuck writeback" affordance — defer.
