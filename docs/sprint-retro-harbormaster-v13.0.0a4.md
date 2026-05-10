# Sprint Retro — Harbormaster v13.0.0a4

**Theme:** Network event filtering — server-side filters on
`/api/network/events`, filter-bar UI in `network.html`, by-source
clickable cross-section dispatch, URL state serialization.

## What shipped

### Server-side filters on `GET /api/network/events`

Four optional query parameters, all AND together:

| Param      | Type      | Behaviour                                |
|------------|-----------|------------------------------------------|
| `tool`     | str       | exact-match on the MCP tool name         |
| `source`   | str       | exact-match on the caller (project name or `"operator"`) |
| `from`     | unix ms   | inclusive lower bound on timestamp        |
| `to`       | unix ms   | inclusive upper bound on timestamp        |

Default behaviour preserved byte-for-byte when all are omitted —
no v10/v11/v12 callers see a behavior change.

Critical contract: filters apply **before** `LIMIT` so an operator
asking "last 10 ask_project events" actually gets 10 even when
other tools dominate recent traffic.

The response echoes the active `filters` dict so the dashboard can
verify the server applied what it asked for:

```
{"count": 10, "events": [...], "filters": {"tool": "ask_project", "source": null, "from": null, "to": null}}
```

`from > to` returns 400.

### `NetworkStore.recent()` extended with filter kwargs

The same kwargs are exposed on the store so other consumers (CLI,
tests, future MCP tools) can filter at the SQL level instead of
post-filtering in Python. Implemented as a single dynamically-built
`WHERE` clause; filter params are bound positionally so SQL injection
is impossible.

### Filter-bar UI in `network.html`

Four controls atop the events panel: two `<select>` dropdowns
(tool + source) and two `<input type="datetime-local">` for the
date range. A `clear` button appears only while at least one filter
is active (`hasFilters()` Alpine getter).

Pre-populated tool options: the eight known MCP tools (`ask_project`,
`delegate_task`, `fan_out_ask`, `recall_qa`, `project_status`,
`list_projects`, `list_hosts`, `project_graph`). Source options
populate from server-side observation as events stream in (defers
to `sourceOptions` array; future a-version can auto-derive from
`/api/network/stats`).

### By-source row → filter dispatch (v12 retro #6)

Each by-source row in the stats panel is now a `<button>` that
dispatches `hm:network:filter` with `{ source: <name> }`. The
events panel listens for the event and calls `applyFilters()`,
which both updates the URL hash and re-fetches with the new filter
applied. Same cross-section pattern as the v10 chat/graph view
toggle.

### URL state serialization (v3.0.0a9 pattern)

Filter state is mirrored into the URL hash on every `applyFilters()`
call (`#tool=ask_project&source=alpha&from=...&to=...`). Hash
(not query string) was chosen so the SSR side ignores it and the
back/forward browser buttons cycle through filter states without
reloading. `_readFilterUrl()` runs on `init()` so a shared link
restores the operator's view.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1346 passed, 3 skipped in 40.1s
```

Test count delta: 1333 → 1346 (+13).

## Tests added (`tests/ui/test_network_event_filtering.py`)

- `test_no_filter_returns_all_events` — backward-compat baseline
- `test_tool_filter_excludes_others`
- `test_source_filter_excludes_others`
- `test_combined_filters_and_together`
- `test_from_to_filter_inclusive`
- `test_from_only_no_upper_bound`
- `test_from_greater_than_to_returns_400`
- `test_response_echoes_active_filters`
- `test_filter_applies_before_limit` — pins the BEFORE-limit
  contract that's the whole point of having filters
- `test_network_html_has_filter_controls` — UI presence
- `test_by_source_row_dispatches_filter_event` — cross-section
  custom event presence
- `test_filter_url_state_serialization_present` — `_writeFilterUrl`
  / `_readFilterUrl` / `history.replaceState` lock-in
- `test_env_override_isolates_store` — fixture sanity check

## Patterns reused

- **URL state via hash** (v3.0.0a9 pattern). Every filterable
  surface in this dashboard now uses the same convention; future
  v14 candidates that introduce new filterable surfaces should
  follow suit.
- **Cross-section dispatch via `window.dispatchEvent`** (v10's
  `hm:network:view` toggle pattern). Keeps the by-source stats
  panel and the events panel decoupled — neither component
  reaches into the other's Alpine state.
- **Server-side filters AND together** (`stats(...)` already used
  the same convention for `since_ms`). Caller composes the filter
  set; the store does the SQL.

## Quality of life

- Operators can now share a URL like
  `/network#tool=ask_project&source=alpha` to bookmark a
  specific filtered view.
- A misbehaving project's by-source row in the stats panel is
  one click away from a focused events table — no manual filter
  typing required.
- The 13.0.0a1 screenshot-diff harness saw the new filter-bar
  layout and would have flagged any inadvertent visual regression
  on the network surface — the regression test pass for the
  utility-migration regression test confirmed only the additive
  `data-filter-controls` chunk landed.
