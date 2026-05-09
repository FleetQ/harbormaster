# Sprint Retro — Harbormaster v2.0.0a2

**Date:** 2026-05-09
**Theme:** Embedding upgrade-in-place. Flipping `[history].fastembed_model`
no longer silently misaligns recall — drift is detected at open time
and resolved by a resumable `harbormaster-mcp reembed` CLI run.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `d14888b` | feat(history): embedding upgrade-in-place + reembed CLI (v2.0.0a2) (#16) |

## Capabilities (this sprint)

### 1 · `embedding_meta` singleton row

Every per-host history db now carries a singleton row (enforced via
`CHECK (id = 1)`):

```sql
CREATE TABLE embedding_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    signature TEXT NOT NULL,
    dim INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    last_reembedded_rowid INTEGER NOT NULL DEFAULT 0
);
```

Seeded by `QAStore.open()` on first run with the configured backend's
signature + dim. Subsequent opens read it and compare.

### 2 · Drift detection (logged-only)

`EmbeddingBackend.signature` is the canonical id used for comparison:
- `FastembedBackend(model="BAAI/bge-small-en-v1.5")` → `"fastembed/BAAI/bge-small-en-v1.5"`
- `FTS5Backend()` → `"fts5"`

When `(stored_signature, stored_dim) != (configured_signature, configured_dim)`,
`QAStore.open()` logs a warning and `has_embedding_drift()` returns
True. **No auto-reembed** — the operator runs the CLI explicitly when
they're ready to spend the embedding compute.

### 3 · `QAStore.reembed(batch_size, resume)`

Walks `qa_log` in committed batches, re-encodes every `question`
against the current backend, and replaces the corresponding `qa_vec`
row. Batch size controls the commit cadence; `resume=True` (default)
starts after `embedding_meta.last_reembedded_rowid`.

Dim change handling: when `stored_dim != configured_dim`, `qa_vec` is
dropped + recreated with the new dim before iteration starts (the old
vectors are already unusable in the new vector space).

Crash safety:
- `last_reembedded_rowid` is updated **after every committed batch**
  (so `--resume` skips already-done rows on retry).
- The identity row `(signature, dim, created_at)` is **only** updated
  after the run completes successfully — a crash mid-run still reports
  drift on the next open. Tested by capturing meta after each batch
  commit and asserting the signature stays at the OLD value until the
  final write.

### 4 · `harbormaster-mcp reembed` subcommand

```
harbormaster-mcp reembed [--host LABEL | --all-hosts]
                         [--batch-size N] [--no-resume]
                         [--dry-run] [--config PATH]
```

Dispatched in `__main__.main` *before* the server's argparse runs, so
bare `harbormaster-mcp` keeps launching the server unchanged. Reports
per-host drift state, then re-embeds (unless `--dry-run`).

### 5 · `EmbeddingBackend.signature` Protocol property

Added to the Protocol with `@property` so concrete backends can compute
it (Fastembed) or return a constant (FTS5). Test stubs across the
codebase updated to provide it. mypy --strict still clean.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — embedding
  upgrade-in-place — was the only one)
- 1 PR opened / merged (#16)
- 14 new unit tests (`tests/unit/test_history_reembed.py`)
- Test suite: 427 → 441 pass, 1 skip
- mypy --strict: 41 → 42 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (drift detection is logged-only;
  existing histories work unchanged with no operator action)
- Lines changed: +834 / -2

## What worked

- **"Detect drift; never auto-act."** Going hands-off on the auto-fix
  side avoided a class of risk (reembed running unattended on a 50k-row
  store after a config flip) without sacrificing the value of the
  detection itself. The warning shows up on every open until it's
  resolved.

- **Identity row vs. progress row separation.** Splitting `(signature,
  dim, created_at)` from `last_reembedded_rowid` made the crash-safety
  invariant trivial to express: only the progress row is touched
  mid-run; the identity row is the "this batch finished" commit.

- **Pre-existing dim_changed branch.** The schema docstring already
  said "switching dim requires a fresh db file" (v1.2). a2 lifts that
  restriction by recreating `qa_vec` instead, which was a 4-line
  change. Past-me did the right thing by stating the constraint
  explicitly — made it cheap to relax later.

- **CLI subcommand dispatch via raw `argv[0]` check.** No new console
  script entry point; no argparse subparsers + bare invocation
  collisions. `if raw_args[0] == "reembed": dispatch elsewhere` keeps
  the server CLI un-touched.

## What to change / next

- **No CI smoke for the reembed CLI.** A future phase that adds a smoke
  test for `harbormaster-mcp reembed --dry-run` against a seeded
  fixture would catch CLI regressions cheaply.

- **No multi-host parallel reembed.** `--all-hosts` runs sequentially.
  At one host per machine that's fine; if the operator has 5+ hosts
  configured, a thread-pool would help. Defer until somebody asks.

- **`embedding_meta` not exposed via UI.** A small badge in the live
  UI dashboard ("History store: drift detected — run `reembed`") would
  make the warning discoverable without tailing logs. Nice-to-have.

## Action items for the next sprint (v2.0.0a3)

1. **Multi-backend: Codex.** Add `harbormaster.backends.codex` mirroring
   `claude.py`. New `[backends.codex]` config block. Per-project
   backend override via `backends_for_project: dict[str, str]`. Soft-fail
   when `codex` binary is absent on $PATH.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Auto-reembed on drift — operator should choose when to spend the
  compute; deliberate.
- Cross-model vector translation — when models disagree, you re-embed.
  No magic.
