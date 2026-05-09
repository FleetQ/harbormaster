# Sprint Retro — Harbormaster v6.0.0a3

**Date:** 2026-05-09
**Theme:** v5.0.0a6 narrowed the dashboard; v6.0.0a3 organises it. Sort
+ group + the existing filter combine into a sharable URL state.

## What landed

| SHA | Subject |
|-----|---------|
| `697000e` | feat(ui): dashboard sort + group controls |

## Capabilities

### 1 · Sort dropdown (3 modes)

```
sort: recent          → last_commit desc (default)
sort: alphabetical    → name ASC
sort: by language     → language ASC, then name ASC within
```

### 2 · Group toggle (flat / by language)

```
group: flat            → one grid (default)
group: by language     → one grid per language, alphabetised group headings
```

When grouped, each language gets a small uppercase heading divider
(`PYTHON`, `JAVASCRIPT`, etc.) and projects without a recognised
manifest cluster under `UNKNOWN`.

### 3 · Server-side language detection

`ProjectInfo` gained a `language` field (default `"unknown"`). New
`_detect_language(path)` helper:

1. Calls `harbormaster.graph.parser.parse_project(path)` — uses the
   existing manifest registry that already detects python / javascript
   / php / rust / go via pyproject.toml / package.json / etc.
2. Falls back to file-existence checks when the manifest itself
   fails to parse (broken JSON, partial pyproject.toml).
3. Returns `"unknown"` only when no marker file is present.

Surfaces in `/api/projects` JSON as `language`.

### 4 · URL state convergence

```
http://harbormaster.local/?filter=auth&sort=alpha&group=language
```

Same default-omit pattern as v3.0.0a9 / v4.0.0a2 / v5.0.0a6. Three
keys (filter / sort / group) coexist; allowlist-validated on read.

## Real numbers

- 1/1 v6.0.0a2-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 7 new tests
- Test suite delta: 717 + 2 skips → **724 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean
- 0 backwards-incompatible changes — `language` field is additive on
  ProjectInfo (default `"unknown"`); new URL params are opt-in

## What worked

- **Reused `parse_project`.** No new manifest detection code; the
  graph.parser registry from v1.0 already had all the language data.
  v6.0.0a3 just exposed it on ProjectInfo.
- **`groupedProjects() → [{label, items}]` shape.** One template
  renders both flat and grouped layouts. Flat = one group with
  empty label; by-language = one group per language. The
  `<h3 x-show="g.label">` toggle handles the heading naturally.
- **Allowlist validation on URL read.** `['last_commit', 'alpha',
  'language'].includes(s)` rejects bogus values from a copy-pasted
  URL — defaults silently apply. Same pattern for group.
- **`localeCompare` for ordering.** Handles non-ASCII project names
  cleanly. The tests' `py-demo`/`js-demo` would also pass with `<`,
  but operators with Cyrillic project names (the user has some)
  benefit from collation-aware sort.

## What to change / next

- **No "language" badge on the card itself.** The heading shows it
  in grouped view, but flat view doesn't surface language at all.
  Operators using flat sort might want a small badge. Defer.
- **Language detection is per-discovery, not cached.** Each
  `/api/projects` call re-runs `parse_project` for every project.
  Acceptable: the parsers are fast (single TOML/JSON read each).
  ManifestCache from v2.0.0a1 could plug in if it shows up in
  profiles.

## Action items for the next sprint (v6.0.0a4)

1. **Keyboard shortcut help popover.** Press `?` to toggle a
   fixed-position popover listing all keyboard shortcuts (graph
   zoom + future). Single source of truth for the shortcut map;
   dashboard header gets a `?` icon for pointer users.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.
- Per-host stale thresholds — defer until observed.
- Language badge on cards — defer.
- ManifestCache for /api/projects — defer until profiled.
