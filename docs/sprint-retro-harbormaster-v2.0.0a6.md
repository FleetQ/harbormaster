# Sprint Retro — Harbormaster v2.0.0a6

**Date:** 2026-05-09
**Theme:** Cross-host recall aggregation. `recall_qa(host="all")`
unifies the per-host Q&A stores into a single score-sorted view, with
per-host failure isolation so one bad store doesn't poison the rest.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(history): cross-host recall aggregation host='all' (#20) |

## Capabilities (this sprint)

### 1 · `recall_qa(host="all")` fan-out

```python
recall_qa(question="...", host="all", top_k=10)
# → {
#     "host": "all",
#     "hosts_searched": ["local", "friday", "jarvis"],
#     "matches": [...sorted by score, capped at top_k...]
#   }
```

Iterates over `[None, *config.hosts.keys()]` in alphabetical order
(local first), runs recall against each per-host store, merges
results, sorts by score descending, caps at `top_k`. Each match
retains its original `host` field so the caller can tell which
machine the trajectory came from.

### 2 · `_recall_one_host()` helper

Extracted the open / recall / close + error mapping into a single
helper used by both the v1 single-host path and the new fan-out path.
Both share the same `tuple[list[QAMatch], str | None]` return
shape — None on success, error string on open or recall failure.

### 3 · Per-host failure isolation

A broken store on one host does NOT block the others. Failures land
in a new `errors: dict[str, str]` field (only present when at least
one host failed). The merged matches still come back from the
healthy hosts. Operators see what's broken without losing the rest of
the result.

### 4 · No SSH involved

Crucially: every per-host store lives **on the local machine** —
filename includes the host label (`qa_friday.db`, `qa_jarvis.db`)
because harbormaster RUNS locally and ROUTES to remote hosts. Recall
just opens N local SQLite files in sequence. No SSH per recall, no
cross-machine network round trip, no auth surface. This is by far the
cheapest cross-host operation harbormaster does.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — cross-host recall)
- 1 PR opened / merged (#20)
- 5 new unit tests in `test_recall_tool.py`
- Test suite: 493 → 498 pass, 1 skip
- mypy --strict: 45 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (`host=None` / `host=<label>` paths unchanged)
- Lines changed: +290 / -34

## What worked

- **No-SSH-needed insight.** When I started planning this phase I
  assumed the per-host stores were *on* the remote hosts — would have
  needed an SSH `cat`-pipe per recall, with all the auth + latency that
  implies. Re-reading the schema docstring (`db_path_for_host`) showed
  the filename is keyed by host label on the LOCAL machine. Cut the
  implementation from "design an SSH recall protocol" to "loop over
  N local files." Saved a phase's worth of complexity.

- **Helper-extracted single-host path.** Pulling
  `_recall_one_host(config, host, ...)` out of the v1 inline code
  meant the new fan-out path didn't have to duplicate the open / close
  / error mapping. Both code paths exercise the SAME helper, so any
  change to recall semantics applies to both — which is exactly what
  you want for a feature that's a fan-out wrapper.

- **`errors` dict only when present.** Adding the `errors` field
  conditionally (only when at least one host failed) keeps the happy-
  path response shape stable. Callers that don't care about errors
  see the same JSON they got in v1; callers that do can check
  `if "errors" in response`.

- **bm25-tolerant score-sort test.** First version of the score-sort
  test asserted specific host ordering, which depends on FTS5 bm25
  scoring quirks. Rewrote to assert "scores are non-increasing across
  hosts" — much more robust to upstream bm25 changes.

## What to change / next

- **Sequential, not parallel.** With 5+ configured hosts, the recall
  latency adds up linearly. A `concurrent.futures.ThreadPoolExecutor`
  per-host call would be a clean improvement; defer until somebody
  has 5+ hosts and notices.

- **No project-name dedup across hosts.** The same project might be
  recorded on multiple hosts (when it's deployed in multiple places).
  Right now the merged result might have the same answer twice. A
  `(project, question)` dedup on top of the score sort would fix it
  but adds complexity.

- **No CI smoke for `host="all"`.** Test coverage is via unit tests
  with on-disk SQLite; smoke jobs don't exercise the multi-host
  config. Adding a config that seeds two host stores + queries with
  `host="all"` would catch wiring regressions across Python versions.

## Action items for the next sprint (v2.0.0a7)

1. **Per-token streaming through Bridge.** The Bridge HTTP-tunnel
   currently delivers full result payload to FleetQ. Wire SSE `chunk`
   events through Pusher events so remote callers see live tokens.
   Final `result` → Pusher event `result`. Coordinated with
   FleetQ-side decoder; feature-flag the chunk events so we don't
   break clients that haven't shipped the chunk handler.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Parallel per-host recall via thread pool — defer until anyone runs
  5+ hosts.
- Cross-host project-name dedup — defer; complexity not justified
  yet.
