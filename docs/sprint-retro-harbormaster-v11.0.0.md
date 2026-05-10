# Harbormaster v11.0.0 — GA Retro (cumulative)

Seven alphas + GA shipped autonomously in one session. Theme:
**harden v10's new surfaces (network log durability + memory editor
security) and finish carry-overs from v9 retros (token instrumentation
+ stateBadge + ?q= prefill + x-data lint).**

## Tags published

| Tag         | Theme                                                         | Tests | Notes |
|-------------|---------------------------------------------------------------|------:|-------|
| v11.0.0a1   | Persistent SQLite-backed network log + caller propagation     | 1116  | Closes v10.a7 deviation; X-Caller-Project header threads through |
| v11.0.0a2   | Per-file memory revision history (last 20 per file)           | 1135  | New `~/.harbormaster/memory_revisions.db`; editor `History` toggle |
| v11.0.0a3   | Bleach-sanitised markdown rendering + live preview pane       | 1154  | `markdown-it-py` added to `[ui]`; split-pane editor with 300ms debounce |
| v11.0.0a4   | Unified stateBadge helper + `?q=` URL pre-fill on askForm     | 1165  | `_state_badge.html` partial loaded globally; cmd-K shareable URLs work |
| v11.0.0a5   | Real backend-reported token usage in SSE `usage` event        | 1181  | Closes v9.0.0a5 deviation; drops `approximate: true` |
| v11.0.0a6   | Caches consolidation: ignored TTL + chatOrder cache + stats   | 1192  | New `/api/network/stats?window=` aggregate endpoint |
| v11.0.0a7   | Async click-handler audit + per-surface SSE heartbeat tuning  | 1207  | Audit found ZERO violations; per-surface defaults 5s/30s/10s |
| **v11.0.0** | GA — cumulative retro                                          | 1207  | This document |

## Cumulative numbers

| Metric                    | v10.0.0 → v11.0.0 |
|---------------------------|-------------------|
| Tests                     | 1097 → 1207 (+110) |
| Source files              | 53 → 56 (+3: `network_store.py`, `memory_revisions.py`, `markdown.py`) |
| New endpoints             | +6 (`memory-history`, `memory-revisions/{id}`, `render-markdown`, `network/stats`, plus `?render=html` query on memory viewer) |
| New top-level config keys | +3 (`heartbeat_interval_streaming_s`, `heartbeat_interval_network_s`, `heartbeat_interval_trace_s`) |
| New persistent state files | +2 (`network_log.db`, `memory_revisions.db`) |
| New dependencies          | +1 (`markdown-it-py>=3.0` in `[ui]`) — bleach was already present |
| Breaking changes          | 0 |

## Confirmation: bleach sanitisation works

`tests/ui/test_markdown_render.py` (19 tests) passes:
- `<script>`, `<style>`, `<iframe>` tags stripped from output.
- Raw HTML attributes like `onclick=` cannot survive on a live `<a>`
  (markdown-it-py escapes raw HTML to entities).
- `javascript:` / `data:` / `vbscript:` URI schemes blocked at the
  link level — no `<a href="javascript:...">` ever appears.
- `http` / `https` / `mailto` survive.
- Standard markdown elements + GFM tables render correctly.
- `language-*` class on `<code>` preserved for syntax-highlighting hooks.

## Confirmation: backend token counters work

`tests/ui/test_backend_token_usage.py` (16 tests) passes:
- `StreamUsage` merges per-message `assistant.usage` + final
  `result.usage` blocks with the result-line being authoritative.
- `_StreamWithUsage` wrapper passes text deltas through transparently
  while exposing `.usage` as a side-channel.
- SSE `usage` event with real backend metadata: payload includes
  `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `model`, plus the legacy chunk
  counts. **Drops `approximate: true`** (closes v9.0.0a5 deviation).
- Falls back to chunk-count approximation when the iterator has no
  `.usage` or `has_real_usage = False`.

## Architecture deltas

- **Persistent observability layer.** `network_log.db` and
  `memory_revisions.db` joined the small set of state files under
  `~/.harbormaster/` (alongside `bridge-state.json`,
  `reembed_history.json`, etc). All four follow the same conventions:
  mode 0600, WAL journal, env-var override for tests.
- **Caller-project propagation.** `X-Caller-Project` header threads
  through `mcp_proxy` → `_stream_dispatch` → `_emit_chunks_then_result`
  for streaming, and through `_dispatch_mcp` → `_record_mcp_dispatch`
  for JSON. Cross-project edges in the network graph are now real
  instead of always "operator → target".
- **Server-side markdown rendering.** New `harbormaster.ui.markdown`
  module exposes `render_safe(md_text) -> str` — markdown-it-py
  parsing + bleach sanitisation. Powers both the memory viewer's
  `?render=html` path and the live-preview endpoint
  `POST /api/render-markdown`. Live preview debounces at 300ms in
  the editor.
- **Backend usage instrumentation.** `claude.py` gained
  `StreamUsage` dataclass + `_StreamWithUsage` iterator wrapper.
  `ask_local_stream` and `ask_remote_stream` capture per-message and
  final-result usage from the stream-json output and surface it via
  the wrapper's `.usage` attribute. The SSE `usage` event consumer
  reads it and drops the `approximate: true` flag when real numbers
  are available.
- **Per-surface heartbeat tuning.** `ServerConfig` gained three
  fields. Streaming defaults 5s, network 30s (events are
  infrequent), trace 10s. Override per-surface via
  `[server] heartbeat_interval_*_s` in `harbormaster.toml`.

## Locked operator decisions honoured

- **Persistence-first for v10's volatile observability state**:
  network log + memory revisions both moved to SQLite with mode 0600
  + WAL + rolling caps. DONE.
- **Security-first markdown rendering**: bleach is the trusted
  boundary; markdown-it-py with `html=False` escapes raw HTML to
  text BEFORE bleach runs. DONE.
- **Vendored only — no new CDN deps**: markdown-it-py is a Python
  package added to the `[ui]` extra. No frontend CDN deps were
  added. DONE.
- **One-version backwards-compat cycle**: v9.0.0a5 `approximate: true`
  flag remained present for callers who read it; v11 only drops the
  flag when real numbers ARE available. DONE.
- **Skip-PR-default**: every alpha + GA shipped via direct merge to
  main from a feat/ branch. DONE.
- **Memory edits are now reversible**: 20-revision per-file rolling
  history with no operator opt-out. DONE.

## Deviations

- **Phase 4 (stateBadge unification)**: only the network status
  pill was migrated to the unified `stateBadgeHtml` helper.
  statusStrip + reembedPanel sites already use a semantically-rich
  class-helper pattern (`bridgeBadgeClass()`, `phaseBadgeClass()`)
  with separate icon helpers; migrating them through
  `stateBadgeHtml` would require a richer signature for marginal
  cleanup. Recorded as v12 candidate `migrate-status-pills-to-
  unified-badge`.
- **Phase 5 (backend tokens)**: only `claude.py` was instrumented.
  `codex.py` would need its own usage-extraction logic mirroring the
  OpenAI Codex output format. Recorded as v12 candidate
  `codex-backend-token-usage`.
- **Phase 1 (network store)**: `NetworkEvent` gained an optional
  `duration_ms` field ahead of v11.0.0a5 to avoid a schema migration
  later. Default `None` keeps existing serializers compatible.
- **Phase 2 (memory revisions)**: PUT endpoint records on every
  write (including no-op writes where content is identical). The
  `bytes_diff` will be 0 in that case — operator can spot it; spec
  did not require de-dup.
- No phase scope-exploded; the two flagged-as-risky phases (a3
  bleach + live preview, a5 backend tokens) shipped clean without
  an aN.5 split.
- **Worktree workflow**: still required the two-step "push branch
  from worktree → fetch + merge from parent main" pattern because
  the parent owns the `main` branch. Documented in v10 retro;
  recorded as v12 candidate `worktree-merge-helper-script`.

## v12 candidate list

Extracted from the seven alpha retros + leftover deferred items:

1. **codex-backend-token-usage** — instrument the Codex backend
   the same way claude.py was instrumented in v11.0.0a5.
2. **migrate-status-pills-to-unified-badge** — flatten
   `bridgeBadgeClass()` / `phaseBadgeClass()` into the unified
   `stateBadgeHtml` helper; needs a richer helper signature.
3. **operator-configurable network-log prune cadence** — `PRUNE_EVERY`
   is hard-coded at 100. Expose via `[server] network_log_prune_every`.
4. **operator-configurable memory revisions cap** — `MAX_REVISIONS_
   PER_FILE` is hard-coded at 20. Expose via `[server]
   memory_revisions_per_file`.
5. **memory revision diff endpoint** — `GET /api/projects/{name}/
   memory-revision-diff?from=<id>&to=<id>` returning a structured
   diff (`difflib.unified_diff`-style) for the editor preview pane.
6. **server-side heartbeat metrics** — `/api/server/heartbeat-metrics`
   exposing per-surface heartbeat-emit counts so operators can tune
   intervals based on real proxy-disconnect rates.
7. **memory revision restore button** — one-click restore from a
   revision (UI calls PUT with the revision's content). Today the
   operator must copy-to-clipboard then paste into the editor.
8. **bleach allowlist tuning** — `<details>`/`<summary>` would let
   memory authors include collapsible sections. Currently stripped.
9. **network stats: per-source breakdown** — extend `/api/network/
   stats` with `by_source` (caller-project counts) so operators can
   spot which calling project dominates the inter-project graph.
10. **chatOrder cache: time-window invalidation** — currently keyed
    off `events.length`. Add a "minutes since last paint" axis so
    the cache invalidates when the chronological labels would
    change.
11. **markdown live preview: lazy first-render** — currently the
    init() seeds the preview synchronously. Defer to the first
    `requestIdleCallback` to keep the editor open transition snappy.
12. **worktree-merge-helper-script** — a `bin/merge-from-worktree`
    helper that automates the "push from worktree → fetch + merge
    from parent main" two-step.

## Final check

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1207 passed, 2 skipped in 39.24s
```

Ready to tag `v11.0.0`, push, and verify on PyPI.
