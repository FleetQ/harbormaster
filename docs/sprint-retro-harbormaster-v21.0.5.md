# Sprint Retro — Harbormaster v21.0.5 (patch)

**Released:** 2026-05-11
**Type:** Patch — operator-reported sidebar UX bugs
**Branch flow:** Directly on `main`

## Why this patch exists

Two operator reports against v21.0.4:

1. **Pin star toggles ON but not OFF.** Clicking the gold `★` glyph in
   the "Pinned" sidebar section did nothing — the glyph was a decorative
   `<span aria-hidden="true">`, not a `<button>`. The actual pin/unpin
   toggle only existed in the per-language list further down.
2. **No UI to ignore a project.** The "Ignored (N)" sidebar section was
   purely a read-only diagnostic of `[ignore].patterns` in the TOML
   config. Operators had no click-driven way to hide a noisy project
   without editing the config file.

## Fixes shipped

### Bug fix — unpin button in the Pinned section

`_partials/_sidebar.html`: promoted the decorative `★` span to a real
`<button @click="togglePin(p.name)">` matching the pattern from the
language list. Visually still gold (`text-warning`); hover dims it to
foreground-muted to telegraph the "click to unpin" affordance.

Live verified: click Pin on a project → row moves to Pinned section
with an Unpin button → click Unpin → row returns to its language group.

### Feature — operator-managed Hide list

End-to-end, server-persistent, distinct from `[ignore].patterns`.

**Server side**:

- New module `src/harbormaster/ui/user_hidden.py` — thread-safe JSON
  state file (`~/.harbormaster/user_hidden.json`, env-overridable via
  `HARBORMASTER_USER_HIDDEN_FILE`). Atomic `tempfile + os.replace`
  writes; every name is re-validated against `_PROJECT_NAME_RE` on
  read so a corrupted state file can't smuggle in a traversal token.
- 3 new endpoints (all in `routes.py`):
  - `GET /api/user-hidden` → `{count, names}`
  - `POST /api/user-hidden` body `{name}` → `{name, added}` (idempotent)
  - `DELETE /api/user-hidden/{name}` → `{name, removed}` (idempotent)
- `/api/projects` filters out user-hidden rows post-cache, so toggling
  Hide/Unhide never invalidates the v21.0.0a8 cross-process
  `projects_cache.json` (which is keyed on filesystem mtime, not view
  preference).
- `/api/ignored-projects` excludes user-hidden names from its diff so
  the "Hidden by you" and "Ignored by config" sections don't
  double-count the same project.

**Client side** (`_partials/_sidebar.html`):

- Each project in the language list gets a new `×` Hide button next
  to the existing pin star. Click POSTs to `/api/user-hidden`,
  refreshes `/api/projects` + `/api/user-hidden`, and the row drops
  out of the sidebar.
- New "Hidden by you (N)" section above the existing "Ignored by
  config (N)" section. Each row carries an `↺` Unhide button that
  DELETEs from `/api/user-hidden` and restores the row.
- Renamed "Ignored (N)" → "Ignored by config (N)" to make the
  distinction explicit (config-driven, read-only).

Live verified end-to-end: click Hide on a project → row moves from
its language list to "Hidden by you (1)" with an Unhide button →
click Unhide → row returns to its language group, Hidden by you
disappears.

### Separation of concerns

| Mechanism | Source | Lifecycle | UI affordance |
|---|---|---|---|
| `[ignore].patterns` | TOML config | static, version-controllable | read-only diagnostic |
| `user_hidden` | dashboard click | dynamic, per-project | Hide / Unhide buttons |
| `pinned` | localStorage | per-browser | Pin / Unpin star |

## Verification

- `ruff check src/ tests/` — clean (after one auto-fix of import sort
  in the new test file)
- `mypy --strict src/harbormaster/` — clean (59 source files, +1 for
  `user_hidden.py`)
- `pytest tests/` — **1905 passed** (+17 for `test_user_hidden.py`),
  1 skipped, 0 failed
- API smoke against live UI: GET / POST / DELETE round-trip OK;
  `/api/projects` correctly excludes hidden rows; invalid names
  rejected with 400
- UI smoke in Chrome MCP: hide + unhide + pin + unpin click flows
  all work end-to-end

## Security considerations

- POST body validated through Pydantic `BaseModel` with
  `model_config = ConfigDict(extra="forbid")` — unknown fields → 422
- Name regex (`_PROJECT_NAME_RE`) enforced at TWO layers (route handler
  + store method) so a future caller of `UserHiddenStore.add` can't
  bypass the gate even if the route validation drifts
- State file written via atomic `tempfile + os.replace` — no torn
  files on crash, no race on concurrent POSTs (process-level
  `threading.Lock`)
- Corrupted state file → empty list (logged warning), never raises
  500 from the read path

## Chain status

Still HALTED. v21.0.5 is the fifth operator-initiated patch in the
2026-05-11 audit cycle. Substantive future work remains a `v22.x`
feature line, not chain resumption.
