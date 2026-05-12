# Sprint Retro — Harbormaster v21.0.8 (patch)

**Released:** 2026-05-12
**Type:** Patch — full-request lazy-fetch in dashboard chat tab
**Branch flow:** Directly on `main`

## Why this patch exists

Operator report on 2026-05-12 (same day as v21.0.7): the chat tab at
`/network#tab=chat` shows truncated request bodies. Expanding a row
only reveals the first 200 chars of the prompt — the rest is gone.

Diagnosis:

- `network_store.py::NetworkStore.record()` hard-capped
  `question_preview` at 200 chars on insert. That column is what the
  chat tab renders both in the collapsed and expanded views.
- The `qa_log` per-host store does keep the full prompt — but it's
  gated behind `[history]`, scoped per host, and joining against it
  from the dashboard would have been a sizable change.
- The user explicitly asked: preview is fine, but a way to see the
  *entire* request on demand.

## Fix shipped

### `question_full` column + idempotent migration

`mcp_calls` gains a new nullable `question_full TEXT` column. Added
in `_connect()` via `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` so
the migration is idempotent:

- Fresh databases: column present from the first `_connect()`.
- v21.0.7-and-older databases: column added on the next process
  start, existing rows keep `question_full=NULL`, the UI falls back
  to the preview.
- Subsequent opens: short-circuit (column already in `table_info`).

### `NetworkStore` API extensions

- `NetworkEvent` dataclass gains an optional `id: int | None` field
  populated by `record()` (from `lastrowid`) and by `recent()`
  (selected from the `id` column).
- `record(question_full=...)` accepts the untrimmed body and persists
  it alongside the 200-char preview. The preview column keeps the
  same cap — list-view payloads stay small.
- New `get_full(event_id) -> {question_full, question_preview} | None`
  used by the API endpoint.

### `GET /api/network/events/{event_id}/full`

New FastAPI route in `ui/routes.py`:

```
GET /api/network/events/{event_id}/full
→ 200 {"event_id": int, "question_full": str | null,
       "question_preview": str}
→ 404 if event_id is unknown
```

Inherits the existing UI auth middleware (Authorization header or
hm-auth cookie).

### Chat-row lazy fetch (template)

`templates/network.html` chat row now owns a per-row state machine
`{ open, full, loading, loadError, loadFull() }`. On first expand,
`loadFull()` issues a single `GET /api/network/events/{id}/full` and
caches the result so re-expanding is free. The expanded view shows:

- A "loading full request…" placeholder while the fetch is in
  flight.
- The error message if the fetch failed (HTTP error, network
  issue).
- The untrimmed body once loaded; falls back to the preview when the
  row was recorded before v21.0.8 (`question_full IS NULL`).
- A small italic hint when falling back: "(showing preview — full
  body not stored for this older event)".

### Call sites wired through

`question_full` flows from every `network_log.record()` caller:

- `tools/_helpers.py::_maybe_record_qa` (success-path mirror)
- `tools/_helpers.py::_record_backend_failure` (v21.0.7
  failure-path mirror)
- `ui/routes.py::_emit_chunks_then_result` (SSE streaming dispatch)
- `ui/routes.py::_record_mcp_dispatch` (non-streaming + fan-out)

All four call sites already had the full text in scope; passing it
as `question_full=...` was a 1-line addition each.

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (59 source files)
- `pytest tests/` — **1928 passed** (+12 vs v21.0.7), 1 skip, 0
  failed
- New tests pin:
  - Fresh and legacy databases both end up with the column after
    `_connect()` — migration is idempotent
  - `record(question_full=...)` persists the untrimmed body uncapped
  - `record()` without `question_full` stores NULL, get_full returns
    NULL — legacy callers still work
  - `recent()` populates `NetworkEvent.id`
  - `get_full(unknown_id)` returns `None`
  - `GET /api/network/events/{id}/full` returns 200 with the full
    body, the preview, and the event_id
  - `GET /api/network/events/{id}/full` 404s on an unknown id
  - The list endpoint `/api/network/events` now surfaces `id` in
    each row so the UI can call the new endpoint
  - Chat row template references `loadFull()`,
    `/api/network/events/{id}/full`, the loading state, the
    fallback hint
- Updated `test_db_file_columns_match_spec` to include the new
  column in the expected schema
- Updated `test_chat_rows_expand_to_full_preview_on_click` for the
  new multi-property `x-data` shape

## Operator playbook (new in v21.0.8)

Open `/network#tab=chat`. Click any row to expand. The dashboard
fetches `/api/network/events/{id}/full` and shows the full request
body — no more 200-char cap on expand. Old rows show the preview
with a hint that the full body wasn't stored for that older event.

## Chain status

Still HALTED on the v21 base. v21.0.8 is the eighth operator-
initiated patch since v21.0.0, and the second on 2026-05-12 (after
v21.0.7's debug-forensics patch earlier in the day).

## Lesson captured

"Preview" as a column name in a write-once log is fine, but it
silently turns into a *contract* the moment the UI binds to it.
Adding a sibling "full" column + lazy fetch on demand is cheaper
than retroactively rewriting the read path against a different
source of truth (qa_log). When introducing a new read-side
endpoint, return both the new field AND the existing preview so the
UI can fall back cleanly for historical rows that don't have the
new field populated yet.
