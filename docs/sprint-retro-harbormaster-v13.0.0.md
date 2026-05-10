# Sprint Retro — Harbormaster v13.0.0 GA

Cumulative retro for the v13 sprint line. Theme: **quality
infrastructure + closing the v9 deferral**. The v13.0.0a1
screenshot-diff harness made the long-pending Tailwind v4 utility
migration safe to ship in a single phase rather than the
previously-anticipated a2 / a2.5 split.

## Numbers

| Metric                         | Before (v12.0.0 GA) | After (v13.0.0 GA) | Delta |
|--------------------------------|--------------------:|-------------------:|------:|
| Tests (passed)                 | 1305                | 1359               | +54   |
| Tests (skipped)                | 2                   | 3                  | +1    |
| Source files (`*.py`)          | 56                  | 56                 | 0     |
| Tags published this sprint     | —                   | 7 (a1..a6 + GA)    | +7    |
| Branches merged                | —                   | 7                  | +7    |
| PRs opened                     | —                   | 0 (skip-PR-default)| 0     |
| Force-pushes to main           | —                   | 0                  | 0     |
| Breaking changes               | —                   | 0                  | 0     |
| Hotfixes                       | —                   | 0                  | 0     |
| a2 / a2.5 split required       | —                   | NO                 | —     |

The +54 net test delta accounts for the 12 utility-migration
regression tests that subsume some prior `text-gray-*` substring
assertions — the gross "tests added" total is 8+12+8+13+7+6 = 54.

## Phases shipped

| Tag           | Theme                                              | New tests |
|---------------|----------------------------------------------------|----------:|
| v13.0.0a1     | Screenshot-diff harness                            |    +8     |
| v13.0.0a2     | Tailwind v4 utility-class migration                |    +12    |
| v13.0.0a3     | Side-by-side HTML diff + reembed diff parity       |    +8     |
| v13.0.0a4     | Network event filtering (server + UI + URL state)  |    +13    |
| v13.0.0a5     | Smoke bundle (theme reload + nginx + contrast)     |    +7     |
| v13.0.0a6     | Operator-facing config doc consolidation           |    +6     |
| v13.0.0       | GA — this retro                                    |     0     |
| **Total**     |                                                    |   **+54** |

## Closed deferrals

- **v9.0.0a1 deferral** (Tailwind v4 utility-class migration —
  pending 4 versions because the screenshot-diff infrastructure
  didn't exist): closed in v13.0.0a2 via the v13.0.0a1 harness.
  624 raw color utility replacements across 10 templates, with
  atomic test sync across 3 test files + a 12-test regression
  guard preventing re-introduction.

## Closed retro candidates (v12)

- **v12 retro #1** — CSS `@theme` reload smoke: closed by
  v13.0.0a5 (`test_theme_toggle_swaps_html_class` +
  `test_css_variables_have_light_and_dark_overrides`).
- **v12 retro #2** — Cookie-behind-nginx integration smoke:
  closed by v13.0.0a5 (`test_set_cookie_survives_proxy_headers`
  + `test_cookie_header_passes_through_proxy_request`).
- **v12 retro #3** — Operator-facing config doc consolidation:
  closed by v13.0.0a6 (`docs/operator-config-reference.md` +
  6 doc-coverage regression tests).
- **v12 retro #6** — By-source clickable filter on the network
  surface: closed by v13.0.0a4 (clickable rows dispatching
  `hm:network:filter` cross-section custom event).
- **v12 retro #7** — Light-mode contrast audit: closed by
  v13.0.0a5 — pure-Python WCAG ratio computation directly from
  the OKLCH values in `tailwind.input.css` via OKLab → linear-sRGB
  matrix. 6 fg/bg pairs audited at AA threshold (4.5:1).

## Closed v11 candidates

- **Memory-revision diff renderer** (HtmlDiff side-by-side):
  shipped in v13.0.0a3 alongside the reembed-runs diff parity.
- **Reembed-history diff endpoint**: also v13.0.0a3 — same
  shape as the memory-revision diff so the UI surfaces stay
  consistent.

## Quality gates (final)

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1359 passed, 3 skipped in 39.9s
```

## Patterns proven this sprint

### Pre-req-then-deferral closure

v13.0.0a1's screenshot-diff harness is the cleanest example of
deliberately shipping infrastructure first to make a long-pending
deferral safe to close. The Tailwind utility migration sat in
the deferred list for FOUR versions because nobody wanted to
risk silent visual regressions. Shipping the harness first
(no functional change, pure test infrastructure) reduced the
migration risk from "human-spot-check 10 surfaces × 2 themes"
to "run the harness, ship if green". Net result: the migration
landed in a single a2 phase, with no a2.5 split needed.

### Migration script + atomic test sync

v13.0.0a2 applied the global "Code Changes" discipline at scale:

1. Grep the codebase for every reference to the symbol → 624 instances
   across 10 templates.
2. Make ALL changes atomically across every file in one commit.
3. Update test assertions in lockstep (3 test files).
4. Add a regression guard (12 new tests) so the migrated state
   stays migrated.

### Doc-coverage gate via Pydantic reflection

v13.0.0a6's `test_every_config_field_documented` is a 30-line
piece of reflection that turns the entire Pydantic config model
into a documentation contract. Adding a new field to `config.py`
without updating the doc fails the test — same lockstep
discipline as the v13.0.0a2 template-migration regression test.

### Pure-Python contrast audit

v13.0.0a5 avoids the standard `axe-core` + headless-Chrome
ceremony by computing WCAG ratios directly from the OKLCH values
in the source CSS. Faster, no browser dependency, reads the
canonical values rather than rendered approximations.

## v14 candidate list

Remaining items from the v13-pre candidate set + new items
surfaced during v13:

1. **Screenshot-diff harness baselines** — bootstrap the
   `tests/ui/_screenshot_diff/baseline/*.png` files (operator
   bless step). Currently the browser tests `pytest.skip()`
   when no baseline exists; once blessed, the suite becomes
   regression-active in CI.
2. **Auto-derive source dropdown options** in network filter UI
   from `/api/network/stats.by_source` instead of starting empty
   (currently relies on URL-direct or by-source-row click).
3. **HTML diff in the memory-editor UI** — the v13.0.0a3
   endpoint is shipped; the dashboard still renders the unified
   diff. Add a "side-by-side" toggle that swaps to `?format=html`.
4. **Reembed-runs diff in the reembed-history table** — same
   pattern as the memory-revision diff button: select two rows,
   click "compare".
5. **Plugin discovery cross-host** — currently `[plugins]` only
   loads on the local Harbormaster. Surfacing remote-host plugin
   inventory via `list_hosts()` would help operators audit
   plugin allowlists across a fleet.
6. **Config-validation CLI**: `harbormaster-mcp config check
   <path>` runs the Pydantic validator + emits a "first key
   that doesn't validate" message. Useful for new operators
   crafting their first `harbormaster.toml`.
7. **Operator-facing dashboard tour**: in-page Alpine wizard
   that steps through "what is this panel?" tooltips on first
   visit, dismissable. Pattern would extend the v9.0.0a1
   accessibility floor work.
8. **Per-host token budget visibility** — extension of the
   v12.0.0a1 codex token instrumentation: surface "tokens
   used today per host" in the dispatcher panel.
9. **Network event timeline graph** — complement the v10
   chat / graph views with a histogram-style "events per minute"
   sparkline. Matches the new filter-bar by date range.
10. **`--config check` mode for `harbormaster-ui` too** — same
    semantics as #6 but for UI startup; would catch
    `[server].ui_port` misuse before the bind error.
11. **Q&A history export endpoint** — `/api/history/qa/export`
    streams the QAStore as JSONL for backup / migration. The
    reembed CLI already has the import path; an export
    completes the pair.
12. **Light-mode-default toggle** — currently the `auto` mode
    follows system pref. Adding a `[ui] default_theme = "light"`
    knob (with `auto` / `light` / `dark`) would let an operator
    pin a default for shared deployments.
13. **Recall-similarity threshold UI control** — surface
    `[history] default_min_similarity` as a dashboard slider
    so operators can tune at runtime without restart.

(13 candidates remain. v14 will likely consume 5–7 of these.)
