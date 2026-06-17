"""Durable-session spike — the Workflow SDK *pattern*, native to harbormaster.

WHY THIS EXISTS
---------------
Vercel's Workflow SDK (workflow-sdk.dev) makes a function durable by recording
every step's input/output in an event log and replaying deterministically from
the last completed step after a crash or deploy. Its headline value for us is
exactly the gap in ``harbormaster.jobs``: today ``JobStore.recover_orphaned``
turns any in-flight ``running`` job into ``failed`` (reason ``server_restart``)
on boot — the work is thrown away, the operator re-delegates.

The SDK's Python beta, however, is a serverless-route / topic-worker model wired
through ``vercel.json`` ``experimentalServices`` and Vercel-managed queues. That
inverts harbormaster's single long-running MCP process and couples us to Vercel.

So this spike proves the cheaper path: we can get the *resume-on-restart* and
*human-in-the-loop suspend* benefits with ~150 lines of stdlib on the SQLite
store harbormaster already runs — no Vercel, no new dependency, no model
inversion. It is throwaway exploratory code, NOT a proposed src/ change.

WHAT IT DEMONSTRATES
--------------------
1. Step memoization + replay: a completed step is never re-run; its recorded
   output is returned (the SDK's "inputs and outputs are recorded in an event
   log ... replays deterministically from where it stopped").
2. Resume-after-crash across process restarts (simulated as separate "boots"
   against the same db file).
3. Human-in-the-loop hook (the SDK's ``BaseHook.wait`` / ``resume``): the
   workflow suspends, consumes nothing, survives a restart, and continues once
   an external approval arrives.

Run:  python3 durable_session_spike.py
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS wf_runs (
    run_id     TEXT PRIMARY KEY,
    workflow   TEXT NOT NULL,
    status     TEXT NOT NULL,            -- running | suspended | completed | failed
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wf_events (
    run_id    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    payload   TEXT NOT NULL,             -- JSON of the step's return value
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, step_name)      -- one terminal event per named step
);
CREATE TABLE IF NOT EXISTS wf_hooks (
    run_id  TEXT NOT NULL,
    token   TEXT NOT NULL,
    status  TEXT NOT NULL,               -- pending | resolved
    payload TEXT,                        -- JSON once resolved
    PRIMARY KEY (run_id, token)
);
"""


class Suspended(Exception):
    """Raised to unwind the workflow when it hits an unresolved hook.

    Mirrors the SDK's "the workflow suspends without consuming resources":
    we stop executing and return control to the caller (the MCP process /
    job worker), which is free to do other work until the hook resolves.
    """

    def __init__(self, token: str):
        super().__init__(f"suspended on hook {token!r}")
        self.token = token


class DurableRun:
    """One resumable run of a workflow, backed by the event log.

    Maps onto harbormaster as: ``run_id`` == ``delegated_jobs.id``, the event
    log == per-step checkpoints the current schema lacks, and ``status`` ==
    the existing ``delegated_jobs.status`` column (with a new ``suspended``
    state replacing the lossy ``running -> failed`` orphan recovery).
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str, workflow: str):
        self.conn = conn
        self.run_id = run_id
        self.workflow = workflow
        conn.execute(
            "INSERT OR IGNORE INTO wf_runs(run_id, workflow, status, created_at)"
            " VALUES (?,?,?,?)",
            (run_id, workflow, "running", time.time()),
        )
        conn.commit()

    # --- step memoization / replay -------------------------------------
    def step(self, name, fn, *args, **kwargs):
        """Run ``fn`` once; on any later replay return its recorded output.

        This is the whole durability trick: a crash between steps loses
        nothing because completed steps are read back from ``wf_events``
        instead of re-executed.
        """
        row = self.conn.execute(
            "SELECT payload FROM wf_events WHERE run_id=? AND step_name=?",
            (self.run_id, name),
        ).fetchone()
        if row is not None:
            print(f"    · step {name!r:14} REPLAYED from log")
            return json.loads(row[0])

        print(f"    · step {name!r:14} EXECUTING")
        result = fn(*args, **kwargs)
        seq = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM wf_events WHERE run_id=?",
            (self.run_id,),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO wf_events(run_id, seq, step_name, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (self.run_id, seq, name, json.dumps(result), time.time()),
        )
        self.conn.commit()
        return result

    # --- human-in-the-loop hook ----------------------------------------
    def wait_for_hook(self, token: str):
        """Resolve to the hook payload, or suspend the run if still pending.

        Equivalent to the SDK Python ``async for event in Approval.wait(...)``.
        """
        row = self.conn.execute(
            "SELECT status, payload FROM wf_hooks WHERE run_id=? AND token=?",
            (self.run_id, token),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO wf_hooks(run_id, token, status) VALUES (?,?, 'pending')",
                (self.run_id, token),
            )
            self._set_status("suspended")
            self.conn.commit()
            raise Suspended(token)
        if row[0] == "pending":
            self._set_status("suspended")
            self.conn.commit()
            raise Suspended(token)
        print(f"    · hook {token!r:14} RESOLVED -> continue")
        return json.loads(row[1])

    def _set_status(self, status: str):
        self.conn.execute(
            "UPDATE wf_runs SET status=? WHERE run_id=?", (status, self.run_id)
        )

    def complete(self):
        self._set_status("completed")
        self.conn.commit()


def resume_hook(conn: sqlite3.Connection, run_id: str, token: str, payload):
    """External actor (operator approval / webhook) resolves a pending hook.

    In harbormaster this is the existing ``answer_clarification`` /
    ``record_delegation_result`` entry point.
    """
    conn.execute(
        "UPDATE wf_hooks SET status='resolved', payload=? WHERE run_id=? AND token=?",
        (json.dumps(payload), run_id, token),
    )
    conn.execute(
        "UPDATE wf_runs SET status='running' WHERE run_id=?", (run_id,)
    )
    conn.commit()


# --------------------------------------------------------------------------
# Demo workflow: a delegated "data analyst" session, the article's example.
# Each boot() opens the db fresh to simulate a separate process (crash/deploy).
# --------------------------------------------------------------------------

def analyst_workflow(run: DurableRun, *, crash_before: str | None = None):
    def fetch():
        return {"rows": 1280, "range": "2026-06-01..2026-06-07"}

    def analyze():
        return {"amer": 2.1, "emea": 1.6, "apac": 0.5}

    def report(numbers):
        return f"AMER ${numbers['amer']}M EMEA ${numbers['emea']}M APAC ${numbers['apac']}M"

    data = run.step("fetch", fetch)
    if crash_before == "analyze":
        raise RuntimeError("simulated crash / launchd reap / deploy restart")
    numbers = run.step("analyze", analyze)
    if crash_before == "report":
        raise RuntimeError("simulated crash / launchd reap / deploy restart")
    summary = run.step("report", report, numbers)

    # Human-in-the-loop: publishing requires operator approval.
    approval = run.wait_for_hook("publish-approval")
    if approval["decision"] != "approved":
        run.step("revise", lambda: f"revised: {summary}")
    else:
        run.step("publish", lambda: f"PUBLISHED: {summary}")
    run.complete()
    return summary


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _status(conn, run_id):
    return conn.execute(
        "SELECT status FROM wf_runs WHERE run_id=?", (run_id,)
    ).fetchone()[0]


def main():
    db = Path("/tmp/harbormaster_durable_spike.db")
    if db.exists():
        db.unlink()
    run_id = "job_demo_001"

    print("BOOT 1  — start session, crash before 'analyze'")
    conn = _open(db)
    try:
        analyst_workflow(DurableRun(conn, run_id, "analyst"), crash_before="analyze")
    except RuntimeError as exc:
        print(f"    ✗ {exc}")
    print(f"    run status: {_status(conn, run_id)}  (current harbormaster would mark this FAILED)")
    conn.close()

    print("\nBOOT 2  — restart, resume; crash again before 'report'")
    conn = _open(db)
    try:
        analyst_workflow(DurableRun(conn, run_id, "analyst"), crash_before="report")
    except RuntimeError as exc:
        print(f"    ✗ {exc}")
    conn.close()

    print("\nBOOT 3  — restart, resume; runs to the approval hook and SUSPENDS")
    conn = _open(db)
    try:
        analyst_workflow(DurableRun(conn, run_id, "analyst"))
    except Suspended as exc:
        print(f"    ⏸ {exc} — 0 compute consumed while waiting")
    print(f"    run status: {_status(conn, run_id)}")
    conn.close()

    print("\nOPERATOR approves out-of-band (answer_clarification equivalent)")
    conn = _open(db)
    resume_hook(conn, run_id, "publish-approval", {"decision": "approved"})
    conn.close()

    print("\nBOOT 4  — restart after approval; replays all, publishes, completes")
    conn = _open(db)
    result = analyst_workflow(DurableRun(conn, run_id, "analyst"))
    print(f"    run status: {_status(conn, run_id)}  result={result!r}")
    conn.close()

    print("\n✓ Same run survived 3 restarts + an indefinite human wait, "
          "re-executing each step exactly once.")


if __name__ == "__main__":
    main()
