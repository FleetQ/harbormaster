# Sprint Retro — Harbormaster v7.0.0a4

**Date:** 2026-05-09
**Theme:** Observability. Capture every reembed run so operators can
see "did anything actually happen since I clicked run now?" without
spelunking through logs.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `7fe6...` | feat(history): rolling reembed run-history log + UI table |

(Hash truncated to suit the retro template; see `git log main` for
the full SHA.)

## Capabilities (this sprint)

### 1 · `~/.harbormaster/reembed_history.json` — rolling 50-record log

New module `src/harbormaster/history/reembed_history.py`:

```
class ReembedRunRecord(BaseModel):
    started_at: float
    finished_at: float
    total: int
    succeeded: int
    failed: int
    cancelled: int
    model: str | None
```

Every completed reembed run (regardless of phase=done|failed|cancelled)
appends one record. The file is mode 0600 (matches the v6 security-
audit convention for `~/.harbormaster/` state files), atomic-write
(tempfile + rename), capped at the 50 most-recent runs.

The runner appends best-effort: every error path is swallowed and
logged. A bad disk path or full disk never crashes the background
thread — at worst we lose one history entry.

Cancelled runs record `cancelled = total - processed` so partial
runs are visually distinguishable from clean failures.

### 2 · `GET /api/history/reembed/runs` endpoint

Wire shape:

```
GET /api/history/reembed/runs
→ 200 {"runs": [{"started_at": …, "finished_at": …,
                 "total": …, "succeeded": …, "failed": …,
                 "cancelled": …, "model": "fts5"}]}
```

Returns `{"runs": []}` when the [history] extra is not installed or
the file doesn't exist (no error — the endpoint is informational).

### 3 · UI: collapsible "recent runs" table

Sits under the reembed panel as a `<details>`. Lazy-loads on first
toggle (no fetch if the user never opens it). When the panel
transitions out of `running` to a terminal phase, the table
auto-refreshes if it was previously opened. Last 5 runs shown,
newest first.

Columns: finished (relative time) · duration · ok · fail · cancel
· model. Counters use semantic colors (emerald/rose/amber).

## Real numbers

- 1/1 v7.0.0a4 phase action items shipped
- 1 feature branch merged (no PR)
- 16 new unit tests (746 → 762 collected; +1 source file → 51 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0 (new module, new endpoint, new UI
  block all additive)

## What worked

- **Lazy-load via `<details>` @toggle.** Zero fetch cost for users
  who never open the panel. Refresh-on-terminal-transition only
  fires after the user has shown interest. Keeps the dashboard fast.
- **Best-effort writer with chmod after rename.** chmod-after-rename
  is the correct order — chmod-before-rename can fail if a different
  process holds the file. The chmod failure is also non-fatal so
  filesystems without POSIX modes (e.g. some FUSE mounts) don't
  break the writer.
- **`record_from_state_and_errors` as a pure function.** The runner
  composes the record from local variables (started_at, errors,
  cancelled flag) — no need to introspect `state` after mutation.
  Tested independently of the runner.

## What to change / next

- **Model label heuristic is shallow.** `_resolve_model_label` only
  knows `fastembed:<model>` and bare backend strings. Future
  embedding backends (e.g. cohere-via-bridge, local-onnx) will need
  matching cases. Acceptable until we ship one — surface as a TODO
  comment in the code.
- **Counter semantics: cancelled = total - processed.** This
  attributes ALL un-processed hosts to "cancelled," which is correct
  for the cancel-mid-run case but slightly fuzzy if cancel arrives
  during host N (host N is "succeeded," hosts N+1..total are
  "cancelled," and the host count math reflects that). Revisit if
  someone gets confused by the table.

## Action items for the next sprint (v7.0.0a5)

1. **`--json` output for `harbormaster-mcp dispatcher status`.** Wrap
   the existing v6.0.0a6 text output with a `--json` flag that emits
   a single JSON object (running, active_workers, queue_depth,
   last_dispatched_at, tools). Default text path unchanged.

## Out-of-scope (still)

- Graphical run-history visualisation (chart of run durations over
  time) — table is enough until someone asks for it.
- Per-host duration tracking — the current record only stores
  outer-run duration. Per-host durations would need a richer
  state-file format and aren't requested.
