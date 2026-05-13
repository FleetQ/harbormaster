# Sprint Retro — Harbormaster v24.0.0a5

**Date:** 2026-05-13
**Theme:** First conservative template split. The 279-line
`reembedPanel` section moves from `dashboard.html` (3064 LOC) into
`_partials/_reembed_panel.html`. Closes part of the v23-retro
"template splits deferred" item.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/templates/_partials/_reembed_panel.html` | new — 279 LOC reembed runner section |
| `src/harbormaster/ui/templates/dashboard.html` | inline section replaced by `{% include "_partials/_reembed_panel.html" %}` |
| `tests/ui/test_empty_states.py` | new `_expand_includes` helper; `_read` uses it |
| `tests/ui/test_state_badges.py` | same — partial-aware read |
| `tests/ui/test_v14_diff_ui_wiring.py` | same |
| `tests/ui/test_v19_dashboard_relayout.py` | same |
| `src/harbormaster/__init__.py` | 24.0.0a4 → 24.0.0a5 |

## Numbers

- 7 files (2 new, 5 modified). ~280 LOC moved (zero net).
- `dashboard.html`: **3064 → 2787 LOC (-277)**. First measurable
  reduction since v19.
- 2023 → 2030 tests (+7 — fixture refactors split a single read
  case into per-marker assertions). mypy --strict clean.
  ruff clean.

## Design notes

### Why reembedPanel as first extraction

- **Most self-contained** — its own `x-data="reembedPanel()"`, its
  own `loadOnce()` lifecycle, doesn't reach into parent scope
- **Largest single x-data scope** (~280 LOC)
- **Stable** — last touched in v6 era; not under active development
- **Test-grep targeted** — multiple tests grep dashboard.html for
  `runDiffOpen` / `data-empty-state="reembed.no-runs"` / phase
  badges, so getting the partial-aware read pattern right unlocks
  the same approach for subsequent extractions

### `_expand_includes` test helper

The 4 affected test files used different read patterns (some via
`(TEMPLATE_DIR / name).read_text()`, one via `TEMPLATE_PATH.read_text()`).
Each got a small `_expand_includes(content, base)` helper inserted
+ its read call wrapped. Five lines of regex; recursive expansion
is not yet supported (no nested partials touched in v24.0.0a5).

### x-data scope NOT inherited

The reembedPanel section in dashboard.html had `x-data="reembedPanel()"`
as its own root. Inside the Jinja `{% include %}`, Alpine evaluates
the partial's HTML in the SAME context as if it were inline. No
scope-inheritance gotchas — verified by the 2030 passing tests
including the relayout grid assertions.

## Lessons

### `wc -l dashboard.html` is the actual signal

The retro-debt label said "split deferred" since v21.0.9. Concrete
measure: dashboard.html LOC. v24.0.0a5 cuts 9% of it
(3064 → 2787) with one extraction. The remaining major scopes
(quickAsk 50 LOC, kpiStrip 110 LOC, projectGrid 200 LOC,
graphPanel+graphZoom 80 LOC, dashboardTabs 13 LOC) could all be
extracted next session but v24.0.0a5 establishes the pattern + the
test helper for any future split.

## Carry-over

- v24.0.0a6: `project_detail.html` template split (same pattern)
- v24.0.0a7: FleetQ webhook subscriber
- v24.0.0 GA

Future template-split opportunities (carry-over, not v24 in-scope):
- dashboard.html: quickAsk, kpiStrip, projectGrid, graphPanel, ...
- project_detail.html: memory editor, recent Q&A, delegate form

## Operator-facing note

After upgrading to v24.0.0a5:

- **No behaviour changes.** The reembed runner panel renders
  identically; its endpoints (`/api/history/reembed/*` and
  `/api/history/state`) are unchanged.
- Source readers: reembed UI lives in
  `src/harbormaster/ui/templates/_partials/_reembed_panel.html`.
  Jinja `{% include %}` from dashboard.html.
- If you write source-grep tests for dashboard content, use the
  `_expand_includes` helper pattern (see `tests/ui/test_v19_dashboard_relayout.py`)
  so the assertion covers content in either dashboard.html or its
  partials.
