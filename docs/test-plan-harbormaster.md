# Harbormaster Test Plan

**Status**: Plan phase
**Sprint**: 2026-05-08
**Reads**: `docs/architecture-harbormaster.md`
**Feeds**: Test phase
**Coverage target**: ≥80% of routing layer; 100% of SSH command builder

---

## 1. Test pyramid

| Layer | Count target (v1.0) | Speed budget |
|-------|----|-----|
| Unit tests | ≥ 60 | total < 5s |
| Integration tests | ≥ 20 | total < 30s (no real SSH/network) |
| E2E smoke | ≥ 8 (manual + scripted) | each ≤ 60s |
| Fuzz / property | ≥ 4 properties | total < 10s |
| Performance benchmarks | ≥ 6 | recorded but not gated |

CI runs unit + integration + fuzz on every push. E2E runs nightly + on tag.

---

## 2. Unit tests (per module)

### `config.py`

- Valid TOML loads into `HarbormasterConfig`.
- Missing required keys surface explicit errors with key path.
- `XDG_CONFIG_HOME` override respected.
- Per-project `.harbormaster.toml` overrides global keys.
- Invalid types (string where int expected) rejected at load.
- Glob expansion respects `~` and `$HOME`.
- `exclude` patterns subtract from `glob` results.
- `require_marker = true` filters dirs lacking CLAUDE.md / .serena/.

### `ssh/command.py`

- Adversarial project names (`'; rm -rf ~`, `$(curl evil)`, backticks, newlines) produce escaped commands where `shlex.split` recovers the original arg list of constant length.
- Adversarial questions (multi-line, quotes, dollar signs) ditto.
- ConnectTimeout / BatchMode / ControlMaster options always present.
- Remote cwd respects `ROUTER_REMOTE_HTDOCS` override.
- Output is `list[str]`, never a single shell string (no shell=True path anywhere).

### `ssh/runner.py`

- Exit code 255 + "Connection refused" → `SshConnectFailed`.
- Exit code 255 + "timed out" → `SshTimeout`.
- Exit code 255 + "Permission denied" → `SshAuthFailed`.
- Stdout JSON tolerates leading login-banner noise.
- Total wrapper timeout enforced regardless of remote behavior.

### `backends/claude.py`

- Builds correct `claude -p` argv for local execution.
- Parses tolerant JSON (markdown fences, multi-chunk streams).
- Returns `BackendResult` with `truncated=true` when output exceeds cap.
- Maps non-zero exit to `BackendError` with stderr tail.

### `tools/projects.py`

- `list_projects` returns rich `ProjectInfo` for local, flat list for remote.
- `project_status` reads git via `subprocess`, parses last 5 commits.
- `project_status` lists Serena memory file names without reading content.

### `tools/ask.py`

- `ask_project` enforces 800-word cap, dumps full output to `/tmp/harbormaster-{run_id}.md` if truncated.
- `fan_out_ask` respects `max_concurrency` semaphore (assert never > N in flight).
- `fan_out_ask` returns per-project results + aggregate summary.

### `storage/trajectories.py`

- Writes run row on completion.
- Updates run row on failure with error details.
- Retention pruner deletes rows older than `trajectory_retention_days` and keeps newer.

### `ui/sse.py`

- Each connected client gets a private `asyncio.Queue`.
- Disconnect cleans up queue.
- Slow client doesn't block fast clients (drop-tail policy on full queue).

---

## 3. Integration tests

### `tests/integration/test_mcp_stdio.py`

- Spawn server as subprocess, speak MCP over stdio, call each tool, assert envelope shape.
- Round-trip schema validation with `mcp` client lib.

### `tests/integration/test_mcp_http.py`

- Bring up server with HTTP/SSE transport, call tools via HTTP client, assert parity with stdio results.
- Bearer token enforcement: missing token → 401, valid token → 200.

### `tests/integration/test_ui_sse.py`

- POST to `/projects/{name}/ask` → returns `run_id` and stream URL.
- Connect to `/stream/{run_id}` → receive `query_started`, ≥1 `query_chunk`, `query_completed` events in order.
- Replay endpoint creates new run with reference to original.

### `tests/integration/test_ssh_local_loopback.py`

- Use `ssh localhost` (rely on local key) to exercise the SSH path without leaving the machine.
- Skip if `ssh localhost` fails (CI shapes vary); document the requirement.

### `tests/integration/test_fleetq_adapter.py`

- Mock FleetQ HTTP server (responses-lib or pytest-httpserver).
- Bridge register / heartbeat / deregister sequence.
- Memory writeback envelope.
- Adapter disabled by default → no requests issued.

---

## 4. E2E smoke matrix

Manual + scripted, run before each tag.

| ID | Scenario | Pass criteria |
|----|----------|---------------|
| E1 | `uvx harbormaster-mcp` cold install + register in Claude Code | `claude mcp list` shows `harbormaster: ✓ Connected` |
| E2 | `list_projects` over 50+ projects | < 1s, all expected projects present |
| E3 | `ask_project pinporn "summarize last commits"` (local) | ≤ 35s, non-empty markdown reply |
| E4 | `ask_project pinporn ... host=friday` (SSH) | ≤ 40s, non-empty reply, no shell-escape leak |
| E5 | `fan_out_ask` over 10 projects | ≤ 60s, per-project + aggregate sections present |
| E6 | UI: load `/`, see project grid + fleet view | < 1s TTFB, no JS errors in console |
| E7 | UI: ask via form, see live SSE stream | tokens appear progressively, completion event lands |
| E8 | UI: replay a historical Q&A | new run row appears; transcript visible |
| E9 (v1.1) | FleetQ Bridge registration appears in fleetq UI | `harbormaster` listed under Bridge endpoints |
| E10 (v1.1) | Trajectory shows up in FleetQ Memory after a run | row visible at `/memory` filtered by `kind=qa_trajectory` |
| E11 (v1.2) | Repeat similar Q&A → cache hit | second call returns < 1s with `cached=true` flag |
| E12 (v1.2) | `recall_qa "auth"` returns relevant past runs | top result relevance > 0.75 cosine |

---

## 5. Fuzz / property tests

Tooling: `hypothesis`.

| Property | Generator | Invariant |
|----------|-----------|-----------|
| SSH command structural integrity | adversarial strings (shell metas, unicode, newlines) | `shlex.split(cmd_string)` recovers original argv length |
| Config robustness | random TOML mutations | either valid → loads, or invalid → typed pydantic error (no crash) |
| Trajectory write idempotence | random run_ids, possibly duplicate | row count never exceeds unique run_id count |
| MCP tool envelope shape | random valid inputs per tool | result satisfies declared JSON Schema |

---

## 6. Performance benchmarks

Recorded via `pytest-benchmark` and persisted to `bench/` for regression tracking. Not gated in CI; reviewed at each tag.

| Benchmark | Target | Source of truth |
|-----------|--------|------------------|
| `list_projects` cold | < 200ms | bench JSON |
| `list_projects` cached | < 30ms | bench JSON |
| `project_status` | < 150ms | bench JSON |
| `fan_out_ask` 10 projects (mocked backend) | < 5s | bench JSON |
| UI cold start TTFB | < 800ms | curl timing |
| SSE event latency p95 | < 50ms | client-side timestamps |

---

## 7. CI matrix

| OS | Python |
|----|--------|
| Ubuntu 24.04 | 3.11, 3.12, 3.13 |
| macOS 14 | 3.12, 3.13 |
| Windows 11 | 3.12 (best-effort; SSH paths may skip) |

Lint: `ruff` + `mypy --strict`.
Format: `ruff format`.
Coverage: `pytest --cov=harbormaster --cov-report=xml`, posted to Codecov.

---

## 8. Security tests

- **Shell injection**: covered by §5 fuzz property.
- **Bleach output**: snapshot tests on a corpus of malicious markdown payloads (script tags, `javascript:` URLs, `<iframe>`, dataURLs) → all stripped.
- **CSP headers**: integration test asserts `Content-Security-Policy` header on all UI responses, no inline scripts allowed.
- **Bearer token**: integration test asserts MCP HTTP rejects missing/invalid tokens with 401, never reflects token in error messages or logs.
- **No secret leakage in logs**: log-capture fixture grep'd for known fixture tokens; assert zero hits.

---

## 9. Manual QA checklist (pre-release)

Run before tagging any v1.x.0:

- [ ] Fresh `pip install harbormaster-mcp` on clean venv works on macOS + Linux.
- [ ] `uvx harbormaster-mcp` works from a directory with no config (uses defaults).
- [ ] First-run experience: clear error if no `[projects]` configured.
- [ ] `claude mcp add` registration succeeds, tools appear under `mcp__harbormaster__*`.
- [ ] UI loads at `http://127.0.0.1:7531`.
- [ ] Asking a question via UI shows live tokens streaming.
- [ ] Stopping the server mid-stream cleans up subprocesses (no orphan `claude` processes).
- [ ] Reading `~/.local/share/harbormaster/audit.jsonl` shows expected events.
- [ ] Removing a project from config does NOT delete its history rows (history preserved).
- [ ] `--version` matches `pyproject.toml`.
- [ ] FleetQ adapter (v1.1+): toggling `[fleetq] enabled = true` registers Bridge within 30s of restart.
- [ ] FleetQ adapter: setting wrong token surfaces `auth_failed` once, then stops retrying (no thundering herd).

---

## 10. Out-of-test (deferred)

- Load testing with thousands of concurrent fan-outs (post-v1).
- Chaos engineering on remote hosts (post-v1).
- Multi-tenant authentication (FleetQ provides this).
- Browser compatibility matrix (Chromium-only target for v1).
