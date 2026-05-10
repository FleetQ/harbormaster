# Harbormaster v10.0.0 — GA Retro (cumulative)

Eight alphas + GA shipped autonomously in one session.

## Tags published

| Tag         | Theme                                              | Tests | Notes |
|-------------|----------------------------------------------------|-------|-------|
| v10.0.0a1   | BUG: record streamed Q&A                            | 1023  | Fix: dashboard / fan-out / project-detail Recent Q&A was empty |
| v10.0.0a2   | BREAKING: remove legacy `chunk` SSE event           | 1023  | One-version deprecation cycle complete (deprecated v9.0.0a5) |
| v10.0.0a3   | Full app-shell layout (fixed topbar/sidebar)        | 1034  | + topbar nav cleanup (drop `/api/projects`, `/api/health`) |
| v10.0.0a4   | `[ignore].patterns` + sidebar indicator             | 1051  | New top-level config section + `/api/ignored-projects` |
| v10.0.0a5   | Per-project memories viewer (read-only)             | 1064  | Vendored marked.js v12.0.2 (35KB) |
| v10.0.0a6   | Memories editor (PUT/POST atomic write-back)        | 1075  | Allowlisted to CLAUDE.md + `.serena/memories/*.md` |
| v10.0.0a7   | Inter-project network graph (Cytoscape vendored)    | 1090  | New `MCPCallLog` ring buffer + Cytoscape v3.30.2 (373KB) |
| v10.0.0a8   | Network chat-view + view-toggle persistence         | 1097  | localStorage-backed view preference |
| **v10.0.0** | GA — cumulative retro                                | 1097  | This document |

## Cumulative numbers

| Metric                    | v9.0.0 → v10.0.0 |
|---------------------------|------------------|
| Tests                     | 1018 → 1097 (+79) |
| Source files              | 52 → 53 (+1: `network_log.py`) |
| Vendored static assets    | 1 (tailwind.css) → 3 (+ marked.min.js, cytoscape.min.js) |
| New top-level config keys | +1 (`[ignore]`) |
| New routes                | +5 (`/network`, `/api/ignored-projects`, `/api/projects/{n}/memories[*]`, `/api/network/events`, `/api/network/stream`) |
| Breaking changes          | 1 (legacy `chunk` SSE event removed) |

## Confirmation: bug #1 (Recent Q&A) is fixed

`tests/ui/test_streaming_qa_writeback.py` (6 tests) passes:
- `test_streamed_call_records_qa_when_enabled` confirms the
  streaming dispatcher writes a row to the local sqlite history
  store after a successful call (assembled answer = "hello world",
  project=alpha, host=local, tool=ask_project).
- `test_streamed_call_records_qa_with_remote_host` confirms the
  per-host db gets the row when `host=friday`.
- Backwards-compat (no record_ctx → no writeback), failure
  swallowing (monkeypatched _maybe_record_qa raise → stream still
  completes), and empty-answer skip all covered.

Operator verification path: open the dashboard, ask a project
something, watch the Recent Q&A panel populate immediately (was
always empty pre-v10.0.0a1).

## Architecture deltas

- **Streaming dispatcher** now mirrors the sync-path `_maybe_record_qa`
  hook (Phase 1). The chunk pipeline emits typed-only events
  (Phase 2). `_emit_chunks_then_result` gained `record_ctx` plumbing
  for both writeback and network instrumentation.
- **Layout shell** is now position-fixed: topbar + sidebar always
  visible; main content has its own scroll context. Stable
  `#hm-topbar` / `#hm-sidebar` / `#hm-main` / `#hm-footer` ids let
  e2e tests target landmarks reliably (Phase 3).
- **Discovery filters** got a top-level `[ignore].patterns` section
  alongside the existing `[projects].exclude`. Two mechanisms is a
  small DX wart but justified by different match semantics
  (Phase 4).
- **Memories surface** introduces an allowlisted file API on the
  project detail page — viewer (a5) + atomic-write editor (a6)
  with belt-and-braces traversal protection.
- **Network observability** adds an in-process `MCPCallLog` ring
  buffer (max 500 events) + SSE fan-out (Phase 7) + chat alternate
  (Phase 8). Both Cytoscape and the chat view consume the same
  feed; toggle persists in localStorage.

## Locked operator decisions honoured

- Inter-project graph viz: Cytoscape.js, vendored (no CDN). DONE.
- External dep policy: vendored only. DONE (tailwind.css from v9,
  marked.min.js + cytoscape.min.js this sprint).
- Inter-project events: all MCP tool calls instrumented. DONE
  (streaming + heartbeat dispatch paths).
- Memories edit scope: per-project only. DONE (CLAUDE.md +
  `.serena/memories/*.md` allowlist; nothing else writeable).
- Layout: full app shell rework. DONE (Phase 3).
- Auth for memories edit: bearer token sufficient, no per-action
  confirm. DONE (existing UI middleware gates the routes).
- Backwards-compat cycle: 1 version. DONE (chunk emitted v9.0.0a5,
  removed v10.0.0a2).

## Deviations

- **Phase 6 (memories editor)**: PUT was specced as update-only;
  shipped as upsert. Symmetrical with REST norms; POST remains the
  exclusive create-with-409-on-conflict path.
- **Worktree / main confusion**: the bash shell resets cwd between
  calls, which initially put my edits on the parent main repo
  instead of the worktree. Caught + reverted before commit; future
  sprints should always edit via worktree-absolute paths and
  delegate the merge step to a self-contained command in the main
  repo. No data loss; recorded for the v11 retro feedback bucket.
- No phase scope-exploded; both flagged-as-risky phases (a3 layout,
  a7 Cytoscape) shipped clean without an aN.5 split.

## v11 candidate list

Extracted from the eight alpha retros + leftover v9 deferred items:

1. **Persistent network log** — replace the in-process ring buffer
   with sqlite-backed storage so events survive restarts and
   aggregate across multiple processes (a7 risk note).
2. **Caller-project propagation** — when a delegated tool calls
   another tool, decorate the call chain with `caller_project` so
   true cross-project edges appear in the graph (a7 risk note).
3. **Memory revision history** — keep last-N versions of CLAUDE.md
   in `.hm-prev/` so overwrites are reversible (a6 risk note).
4. **Live preview on memory editor** — markdown preview pane while
   the textarea is open (a6 risk note).
5. **Live token preview** — a real preview-while-typing pane in
   the ask form (deferred from v9.0.0a3).
6. **Bleach-sanitised memory rendering** — server-side HTML sanitise
   if memories ever go beyond operator-trusted scope (a5 risk note).
7. **`/api/ignored-projects` caching** — cache the diff in
   `manifest_cache.py` if the sidebar polls it more than once per
   page (a4 risk note).
8. **Cookie-backed bearer for SSE** — EventSource can't send a
   bearer header; cookie-back the token so non-loopback installs
   are properly auth'd (a7 risk note).
9. **Heartbeat tighten-up** — operator-configurable heartbeat
   interval per surface; today the network stream and the MCP
   stream share the same `_HEARTBEAT_INTERVAL_S = 5.0`.
10. **Reverse-cache `chatOrder()`** — minor optimisation for the
    chat view if buffer cap grows (a8 risk note).
11. **Cumulative network metrics** — a `/api/network/stats`
    endpoint summarising per-tool / per-project call counts so the
    operator can spot anomalies without scrolling chat.
12. **Memory tagging UI** — sidebar pane to add labels to memory
    files so the read-only viewer can filter by tag (operator
    feedback during Phase 5 review).

## Final check

```
mypy --strict src/harbormaster   →  Success: no issues found in 53 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1097 passed, 2 skipped in 36.65s
```

Ready to tag `v10.0.0`, push, and verify on PyPI.
