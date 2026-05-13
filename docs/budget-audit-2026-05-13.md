# Hardcoded Budget Audit — 2026-05-13

Action item #5 from `retro/retro-2026-05-13.md`: v22 added writes
and async to a code path whose budgets were sized for v1's read-only
shape. This audit enumerates every numeric budget in `src/harbormaster/`
and flags the ones that have NOT been reconsidered since v22.

## Triage legend

- ✅ **OK** — sized appropriately for current shape; reconsidered or
  obviously correct
- ⚠️ **Revisit** — sized for v1 read-only; should be re-evaluated
  against v22 writes/async usage patterns
- 🟡 **Operator-overridable** — has TOML / param override, default is
  reasonable
- 🛠️ **Already flagged** — captured in retro / memory; pending action

---

## 1. Turn budgets (per-tool)

| Field | Default | Set in | Status |
|---|---:|---|---|
| `delegate_task(max_turns=...)` | 10 | `tools/delegate.py:46` | 🛠️ Already lifted — v22.0.1 made caller-overridable. Default 10 stays for backward-compat. **Empirical recipe in v22-final-summary memory: 5-10 read-only, 15-25 single-file, 50-80 multi-file feature, 100+ refactor.** |
| `delegate_task` worker uses `job.max_turns` | persisted per-job | `jobs/worker.py:106` | ✅ Wired correctly post-v22.0.1 |
| `ask_project(max_turns=...)` | 5 | `tools/ask.py:16` | ✅ OK for Q&A. ask_project is read-only by design — 5 turns is appropriate. |
| `fan_out_ask(max_turns=...)` | 3 | `tools/fan_out.py:42` | ✅ OK — fan-out is intentionally shallow per target |
| `fan_out_ask(synthesis_max_turns=...)` | 5 | `tools/fan_out.py:44` | ✅ OK — synthesis is single-aggregator |
| `triples_llm.extract(max_turns=1)` | 1 | `fleetq/triples_llm.py:207` | ✅ OK — single-shot extractor by design |

**Verdict**: turn budgets are sane post-v22.0.1. The
`delegate_task` ceiling is what caught us; it's now caller-supplied.

---

## 2. Subprocess timeouts (claude / codex backends)

| Field | Default | Set in | Status |
|---|---:|---|---|
| `BackendConfig.timeout_local` | 60s | `config.py:38` | ⚠️ **Revisit.** Sized for v1 read-only Q&A (~30s typical). v22 async writes with `max_turns=80` take ~800s. Operator config already bumped to 600s. **Default should bump to 300s** so unconfigured operators don't hit it on first real write delegation. |
| `BackendConfig.timeout_remote` | 120s | `config.py:39` | ⚠️ **Revisit.** Same logic — SSH delegations with writes need more headroom. **Default should bump to 600s.** |
| `HostConfig.connect_timeout` | 10s | `config.py:84` | ✅ OK — SSH connect should be fast |
| `HostConfig.total_timeout` | 120s | `config.py:85` | ⚠️ **Revisit.** Used by SSH stream paths; same v1-read-only sizing as `timeout_remote`. **Default should bump to 600s.** |
| `proc.wait(timeout=2)` (TERM grace) | 2s | `claude.py:282,445`, `codex.py:384,460` | ✅ OK — grace period before SIGKILL |
| `proc.wait(timeout=5)` (final read) | 5s | `claude.py:301,473`, `codex.py:409,485` | ✅ OK — drain stdout/stderr after exit |
| `git log subprocess timeout=5` | 5s | `projects.py:298`, `tools/projects.py:80,89,96,123` | ✅ OK — `git log` is fast even on large repos |
| `urlopen timeout=5` (dispatcher CLI) | 5s | `dispatcher_cli.py:161` | ✅ OK — local loopback fetch |
| `sqlite3.connect timeout=5.0` (dispatcher metrics) | 5s | `dispatcher_metrics_store.py:66` | ✅ OK — local file open |

**Recommendation for v23**:

```python
# config.py
class BackendConfig(BaseModel):
    timeout_local: int = Field(default=300, gt=0)   # was 60
    timeout_remote: int = Field(default=600, gt=0)  # was 120

class HostConfig(BaseModel):
    total_timeout: int = Field(default=600, gt=0)   # was 120
```

Defaults shift to v22-realistic budgets. Existing operator TOMLs with
explicit values are unaffected (override wins). New operators get
reasonable headroom for first-time async writes.

---

## 3. Output caps

| Field | Default | Set in | Status |
|---|---:|---|---|
| `BackendConfig.output_word_cap` | 800 | `config.py:40` | ⚠️ **Revisit.** Sized for v1's "return a 500-word markdown summary" pattern. v22 write-mode delegations return change-summaries (files-changed list, follow-ups) — typically 200-400 words. Could STAY at 800 (slack is fine) but worth noting it was never reconsidered. **Action: leave as-is, document the v22 prompt expects ≤500 words.** |
| `auto_ground_max_chars` | 8000 | `config.py:180` | ✅ OK — recall context cap, sized for v1.2 phase 4 |
| Prompt suffix "Return markdown under 500 words." | 500 word target | `tools/delegate.py:18,28` | ✅ OK — matches output_word_cap headroom |

---

## 4. Heartbeat intervals (SSE / Bridge)

| Field | Default | Set in | Status |
|---|---:|---|---|
| `heartbeat_interval_streaming_s` | 5.0 | `config.py:116` | ✅ OK — long claude-p invocations need frequent keep-alive |
| `heartbeat_interval_network_s` | 30.0 | `config.py:117` | ✅ OK — used by `/api/network/stream` AND v22.2.0 `/api/delegated-jobs/stream` — events are infrequent, 30s is right |
| `heartbeat_interval_trace_s` | 10.0 | `config.py:118` | ✅ OK — mid-frequency dispatcher trace |
| `fleetq.heartbeat_interval` | 30 | `config.py:147` | ✅ OK — Bridge keepalive |
| `optimistic_stale_seconds` | 5 | `config.py:202` | ✅ OK — v6.0.0a2 optimistic escalation threshold |

---

## 5. Concurrency

| Field | Default | Set in | Status |
|---|---:|---|---|
| `dispatcher_max_workers` | 1 | `config.py:154` | ✅ OK — single-worker safe default, opt-in to bounded pool |
| `parallel_recall_max_workers` | 4 | `config.py:189` | ✅ OK — recall is read-heavy, bounded |
| `JobWorker.poll_interval_s` | 0.5 | `jobs/worker.py:64` | ✅ OK — sleep when queue empty; not a hot loop |
| **JobWorker concurrency** | **1 (process-wide)** | `jobs/subsystem.py` | 🛠️ **Already flagged** — multi-worker concurrency is in v22 out-of-scope list as v23.0.0a? candidate. Atomic claim already supports it; needs config knob `[delegate] worker_count = N`. |
| `dispatcher_max_workers le=16` cap | 16 | `config.py:154` | ✅ OK — hard ceiling matches macOS default file-descriptor / process limits |

---

## 6. Retention

| Field | Default | Set in | Status |
|---|---:|---|---|
| `trajectory_retention_days` | 90 | `config.py:104` | ✅ OK — sized for a quarter |
| `retain_recent_k` | 1000 | `config.py:171` | ✅ OK — qa_log recent cap |
| `retain_top_recalled_r` | 100 | `config.py:172` | ✅ OK — retain frequently-recalled answers |
| `network_log_max_rows` | 5000 | `config.py:223` | ✅ OK — ring-buffer-like cap |
| `memory_revisions_per_file` | 20 | `config.py:224` | ✅ OK |
| `kg_max_triples_per_call` | 50 | `config.py:136` | ✅ OK — heuristic extractor cap |
| `kg_llm_max_triples` | 20 | `config.py:144` | ✅ OK — LLM extractor cap |
| **`delegated_jobs` retention** | **no cap** | `jobs/store.py` | ⚠️ **Revisit.** v22 introduced `delegated_jobs.db` with NO retention policy. Currently grows unbounded. **Action: add `[delegate] retain_recent_k = 1000` config + cleanup pass on subsystem boot.** (Mirrors history retention shape.) |

---

## 7. Recall / history tuning

| Field | Default | Set in | Status |
|---|---:|---|---|
| `default_top_k` | 5 | `config.py:176` | ✅ OK — recall_qa top-k |
| `default_min_similarity` | 0.6 | `config.py:177` | ✅ OK — embedding similarity floor |
| `auto_ground_top_k` | 3 | `config.py:179` | ✅ OK — prepended-context cap |
| `auto_ground_min_similarity` | 0.55 | `config.py:181` | ✅ OK — slightly looser for ground context |
| `embedding_dim` | 384 | `config.py:169` | ✅ OK — fastembed BAAI/bge-small-en-v1.5 native dim |

---

## 8. v22 blocking-await timeouts

| Field | Default | Set in | Status |
|---|---:|---|---|
| `await_delegated_task(timeout_seconds=...)` | 900 (15 min) | `tools/await_jobs.py:35` | ✅ OK — caller-overridable per-call |
| `await_inbox(timeout_seconds=...)` | 900 (15 min) | `tools/await_jobs.py:74` | ✅ OK — caller-overridable |
| **HTTP server / proxy request timeout** | n/a (held open) | uvicorn default | ✅ OK — local loopback, no reverse proxy in operator setup |

---

## 9. Ports

| Field | Default | Set in | Status |
|---|---:|---|---|
| `ui_port` | 7531 | `config.py:101` | ✅ OK — operator-overridable |
| `mcp_http_port` | 7532 | `config.py:102` | ✅ OK — operator-overridable |

---

## Summary

### Items needing v23 action (4 candidates)

1. **`BackendConfig.timeout_local: 60 → 300`** — sized for v1 Q&A,
   now tight for v22 writes
2. **`BackendConfig.timeout_remote: 120 → 600`** — same logic for SSH
3. **`HostConfig.total_timeout: 120 → 600`** — same logic for SSH streams
4. **Add `delegated_jobs` retention** — `[delegate] retain_recent_k`
   (or similar) + cleanup on subsystem boot. Currently unbounded
   growth.

### Items already-flagged (1)

1. **JobWorker single-worker concurrency** — multi-worker concurrency
   noted as v23 candidate in v22-final-summary. Atomic claim ready;
   needs config knob.

### Items intentionally NOT changing (everything else)

All other budgets are either:
- operator-overridable with reasonable defaults
- read-only-path values that v22 didn't disturb
- internal subprocess grace periods (proper for their purpose)

## Implementation sketch for v23.0.0a? (timeout + retention bumps)

Single-commit change:

```python
# src/harbormaster/config.py — increase defaults to v22-realistic
class BackendConfig(BaseModel):
    timeout_local: int = Field(default=300, gt=0)
    timeout_remote: int = Field(default=600, gt=0)

class HostConfig(BaseModel):
    total_timeout: int = Field(default=600, gt=0)
```

```python
# new — JobStore retention
class DelegateConfig(BaseModel):
    retain_recent_k: int = Field(default=1000, gt=0)

# jobs/store.py — prune in _apply_migrations after migration:
def _prune_old_jobs(self, retain: int) -> int:
    with self._lock:
        cur = self._conn.execute(
            "DELETE FROM delegated_jobs "
            "WHERE id NOT IN ("
            "  SELECT id FROM delegated_jobs "
            "  ORDER BY queued_at DESC LIMIT ?"
            ")", (retain,),
        )
        return cur.rowcount
```

Tests: existing `_apply_migrations` test pattern extended to assert
pruning fires once.

Risk: **timeout bumps could mask real hangs**. Defenses:
- The cid forensics path (v21.0.7) still captures stderr_tail on
  timeout
- `incident-playbook` memory entry #1 still triggers correctly on
  `max_turns_reached` regardless of timeout

Estimated effort: 1 alpha ship (≤ 1 hour). Suggested slot:
**v23.0.0a2** (after the v23.0.0a1 routes.py split lands).

## Cross-references

- `retro/retro-2026-05-13.md` — original action item
- `v22-final-summary` Serena memory — operator-facing upgrade
  guidance + empirical max_turns / timeout_seconds tables
- `incident-playbook` Serena memory — silent claude exit diagnosis
- `v21.0.3-v21.0.9-patch-arc` memory — v21.0.7 cid forensics pattern
  that backstops any timeout regression
