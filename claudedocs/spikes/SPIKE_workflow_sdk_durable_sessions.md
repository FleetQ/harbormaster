# SPIKE — Vercel Workflow SDK for harbormaster durable sessions

**Date:** 2026-06-18
**Branch:** feat/provider-agnostic-orchestrator
**Status:** Spike complete — exploratory only, no `src/` changes
**Artifacts:** `durable_session_spike.py` (runnable, stdlib-only) + this doc
**Verdict:** **Do NOT adopt the Workflow SDK. Adopt its *pattern* natively (~150 LOC on the store we already run).**

---

## 1. The question

My eve research recommended a spike of the [Workflow SDK](https://workflow-sdk.dev/)
(the open-source durability layer under Vercel eve) for harbormaster durable
sessions. Should harbormaster adopt it to fix the "in-flight work is lost on
restart" problem?

## 2. The harbormaster gap, confirmed in code

`src/harbormaster/jobs/` is a SQLite-backed async delegate queue. A `JobWorker`
daemon thread claims a `queued` job, flips it to `running`, then makes **one
opaque blocking call** to `run_backend(...)` (spawns `claude -p` for minutes→hours)
and finally marks it `completed`/`failed`.

The durability unit is the **whole job**, with no checkpoint of anything inside it.
On boot, `JobStore.recover_orphaned()` does this (`store.py:769`):

```sql
UPDATE delegated_jobs SET status='failed', error='server_restart'
WHERE status='running';
```

So a crash, a launchd reap (we have a whole memory on launchd SIGTERMing the
process group), or a deploy **throws away every in-flight job** and forces the
operator to re-delegate. Clarifications waiting via the `job_clarifications`
table have the analogous problem. **This is exactly the pain the SDK markets
against.**

## 3. What the Workflow SDK actually is (Python beta)

From the docs (`workflow-sdk.dev/docs/getting-started/python`, `pip install vercel`):

- `@wf.workflow` / `@wf.step` decorators. "All inputs and outputs are recorded in
  an event log. If a deploy or crash happens, the system replays execution
  deterministically from where it stopped." → **the right idea.**
- Human-in-the-loop via Pydantic `workflow.BaseHook` + `Approval.wait(token=...)`
  / `approval.resume(token=...)`. → maps cleanly onto our `request_clarification`
  / `answer_clarification`.
- **BUT** configuration is `vercel.json` → `experimentalServices: {type:"worker",
  entrypoint:..., topics:["__wkf_*"]}`. Each step "compiles into an isolated
  route"; the workflow "compiles into a route that orchestrates execution."

### Why that's a structural mismatch for us

| Dimension | Workflow SDK (Python beta) | harbormaster |
|---|---|---|
| Execution model | Serverless **routes** invoked by a platform orchestrator over **topics** | Single **long-running MCP process** + daemon-thread worker |
| Durability backend | Vercel-managed event log / queue | Self-hosted SQLite on fleetq-01 |
| Deploy target | Documented path = **Vercel** (`vercel deploy`). "Run anywhere / Docker / self-host" is shown only for the **TypeScript** SDK | Self-hosted, no Vercel |
| Maturity | **Beta**, "APIs and behavior may change" | Mature, ~1900 tests |
| Language fit | Python beta exists ✓ | Python ✓ |

Adopting the SDK means inverting harbormaster's process model into Vercel-managed
serverless functions and coupling our durability to a Vercel-hosted backend. The
self-host story for the **Python** event-log backend is undocumented today.

### The deeper reason it buys us little even if self-hosted

The SDK's headline feature is **deterministic step replay**. But harbormaster's
"step" is a single hour-long, **non-deterministic `claude -p` subprocess**. You
cannot replay half an LLM agent run. So the SDK's core value applies only to the
*orchestration around* the subprocess — orphan recovery, retries, the
clarification wait — which is a small, well-bounded surface we already own.

## 4. The cheaper path — proven runnable

`durable_session_spike.py` implements the SDK's pattern in **stdlib only**, on the
same SQLite paradigm `jobs/` already uses: an append-only `wf_events` log, a
`step()` that memoizes+replays by `(run_id, step_name)`, and a `wait_for_hook()`
/ `resume_hook()` pair for human-in-the-loop.

Output (a delegated analyst session surviving **3 restarts + an indefinite human
wait**, each step executed exactly once):

```
BOOT 1  crash before 'analyze' → step 'fetch' EXECUTING; status: running
BOOT 2  resume → 'fetch' REPLAYED, 'analyze' EXECUTING; crash before 'report'
BOOT 3  resume → 'fetch'/'analyze' REPLAYED, 'report' EXECUTING
        ⏸ suspended on hook 'publish-approval' — 0 compute consumed while waiting
OPERATOR approves out-of-band (answer_clarification equivalent)
BOOT 4  resume → all REPLAYED, hook RESOLVED, 'publish' EXECUTING; status: completed
```

Direct contrast: where this resumes, today's `recover_orphaned()` would have
marked the job `failed` at BOOT 1.

## 5. Recommendation

**Reject the SDK; build the pattern natively.** Concretely, when/if we decide to
implement (separate from this spike):

1. Add a `wf_events`-style checkpoint table keyed to `delegated_jobs.id`, and a
   `suspended` status alongside the existing ones in `schema.py`.
2. Change `recover_orphaned()` from `running → failed` to `running → re-claimable`
   for jobs whose work is resumable, leaving non-resumable subprocess jobs as the
   one honest `failed` case (can't replay a half-finished LLM run).
3. Fold the existing `job_clarifications` wait onto the same hook primitive so a
   clarification survives a restart instead of stranding the job.

**Cost/benefit:** ~150 LOC + tests, zero new dependencies, zero Vercel coupling,
no process-model inversion. Keep watching the SDK's Python self-host story; revisit
only if a self-hostable event-log backend ships and we ever want cross-language
(TS) agent workflows.

## 6. Sources
- workflow-sdk.dev/docs/getting-started/python · /docs/ai · landing page
- vercel.com/blog/introducing-eve (durability claims)
- harbormaster: `jobs/{schema,store,worker,subsystem}.py`, `tools/{delegate,clarify}.py`
