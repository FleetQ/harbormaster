# Sprint Retro — Harbormaster v13.0.0a3

**Theme:** Side-by-side HTML diff renderer + reembed-history diff
parity. Two diff-related polish items combined.

## What shipped

### `?format=html` on the memory-revision diff endpoint

`GET /api/projects/{name}/memory-revisions/diff` (v12.0.0a4) gained
a `format` query parameter:

- `?format=unified` (default — v12.0.0a4 contract preserved
  byte-for-byte). Returns `text/plain` unified diff.
- `?format=html` — returns `text/html` side-by-side diff via
  `difflib.HtmlDiff().make_table` with line numbers and change
  highlights (`td.diff_chg`, `td.diff_add`, `td.diff_sub`).
- Unknown `format` → 400 ("format must be 'unified' (default) or
  'html'").

The HTML output is a bare `<table class="diff">…</table>` fragment
with no surrounding `<html>` / `<style>` chrome — the dashboard
provides its own styles in `base.html` and the fragment fits
straight into a container. It also passes through the v12.0.0a4
extended bleach allowlist unchanged (no new whitelist additions
required).

### `GET /api/history/reembed/runs/diff?from=I&to=J`

New endpoint. Mirrors the memory-revision diff pattern for the
v7.0.0a4 reembed history. Indices are zero-based offsets into the
list returned by `/api/history/reembed/runs`.

Response shape:

```
{
  "from_index": 0,
  "to_index": 1,
  "from": <ReembedRunRecord dict>,
  "to":   <ReembedRunRecord dict>,
  "delta": {
    "duration_seconds": 15.0,    # to.duration - from.duration
    "total":     +10,
    "succeeded": +13,
    "failed":     -3,
    "cancelled":   0,
    "model_changed": false       # explicit, no string compare in UI
  }
}
```

Status codes:

- 200 — both indices in range.
- 404 — either index out of range (negative or ≥ len).
- 503 — `[history]` extra not installed (mirrors the existing
  `/api/history/reembed/cancel` behavior).

The endpoint returns both full `ReembedRunRecord` dicts so the UI
can render the side-by-side without a second fetch — same trick
the memory-revision diff uses with revision content.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1333 passed, 3 skipped in 40.2s
```

Test count delta: 1325 → 1333 (+8 tests for both endpoints).

## Tests added (`tests/ui/test_html_diff_and_reembed_diff.py`)

- `test_html_diff_returns_html_table` — `format=html` returns
  `text/html` with `<table class="diff">` + `fromdesc` /
  `todesc` headers.
- `test_html_diff_two_revisions` — `from=A&to=B` works with
  `format=html`; output contains a change-highlight class.
- `test_unified_format_default_preserved` — explicit guard against
  accidentally flipping the v12.0.0a4 default in this refactor.
- `test_unknown_format_returns_400` — invalid `format` value is
  rejected with 400.
- `test_reembed_runs_diff_basic` — synthetic 2-row history,
  validates per-field delta + duration computation.
- `test_reembed_runs_diff_model_changed` — model-change boolean
  flips when models differ.
- `test_reembed_runs_diff_404_when_index_oob` — both negative and
  past-end indices 404.
- `test_reembed_runs_diff_returns_full_records` — both `from` /
  `to` records present in response (no second-fetch needed).

## Patterns reused

### Two-item phase (same as v12.0.0a4 / a5)

When an additive feature has an obvious neighbor that benefits from
the same plumbing, ship together. The `format=html` flag landing
in the same retro as the reembed-runs/diff endpoint reinforces the
"diff endpoints look the same shape" rule for v14+ work.

### Default-preserved-by-test

`test_unified_format_default_preserved` is the same pattern as
`test_default_tolerance_constant` from v13.0.0a1's screenshot-diff
helper — when an endpoint gains an option, pin the previous
default in a dedicated test so a careless refactor can't silently
flip it.

## Quality of life

- The dashboard memory-editor "Diff" panel can now request
  `?format=html` and drop the response straight into a `<div>` —
  no client-side line-by-line table reconstruction.
- The reembed-history table can compare any two completed runs
  with one fetch, surfacing per-field deltas without parsing
  timestamps client-side.
- Both endpoints follow the existing two-step diff convention:
  `from` defaults to the comparator, `to` is optional / required
  depending on the natural shape — matches v12.0.0a4 muscle memory.
