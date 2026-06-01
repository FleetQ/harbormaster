"""Shared helpers for tool implementations (private to harbormaster.tools).

Translates between the typed Backend interface (which raises BackendError on
failure) and the MCP user-facing string contract (which returns 'Error: ...'
prefixed strings so the envelope stays consistent across tools).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections.abc import Iterator
from pathlib import Path

from harbormaster.backends import BackendError, get_backend_for_project
from harbormaster.config import HarbormasterConfig
from harbormaster.instruction import (
    PacketKind,
    build_packet,
    execution_mode_for,
    packet_kind_for_delegate,
)
from harbormaster.orchestrators import (
    detect_client_orchestrator,
    get_adapter,
    resolve_orchestrator,
)
from harbormaster.projects import resolve_project, validate_project_name
from harbormaster.ssh import is_remote

logger = logging.getLogger("harbormaster.tools._helpers")


def _new_correlation_id() -> str:
    """Short, unique-enough token to cross-reference an error string
    returned to the agent against the corresponding log line + network_log
    row. 8 hex chars = 4B entropy — collisions effectively impossible
    within a session's failure window."""
    return secrets.token_hex(4)


def _record_backend_failure(
    *,
    project_name: str,
    host: str | None,
    prompt: str,
    tool: str,
    error: BackendError,
    elapsed_ms: int,
    correlation_id: str,
) -> None:
    """v21.0.7: capture forensic data when a backend call fails.

    Emits one structured WARNING log line and mirrors the failure into
    the UI network_log (``mcp_calls`` table) with ``status='error'`` so
    the dashboard Activity / Timeline tabs surface failed calls — not
    just successful ones. Mirrors the success-path tool-dispatch
    logging pattern established in v21.0.6 (see
    v21.0.3-v21.0.6-patch-arc memory: tool-dispatch-layer logging,
    never transport-layer).

    Best-effort: any failure inside this helper is swallowed. The hot
    path (returning the error string to the agent) must never be
    blocked by instrumentation.
    """
    logger.warning(
        "backend_failure cid=%s tool=%s project=%s host=%s code=%s "
        "elapsed_ms=%d message=%r",
        correlation_id,
        tool,
        project_name,
        host or "local",
        error.code,
        elapsed_ms,
        # Cap the captured message at 500 chars in case it includes a
        # long stderr tail (claude -p rate-limit JSON, etc.). The full
        # text is still in the agent-facing return string; the
        # operator can rerun with DEBUG log level for more detail.
        str(error)[:500],
    )

    # Mirror to network_log so dashboard Activity / Timeline include
    # this failure. Lazy import — when [ui] extra isn't installed
    # (pure stdio MCP setup) the ImportError is swallowed and we
    # no-op, preserving the no-required-ui invariant.
    try:
        from harbormaster.ui.network_log import (
            current_caller_project,
            network_log,
        )

        network_log.record(
            caller=current_caller_project() or "operator",
            target=project_name,
            tool=tool,
            status="error",
            question_preview=prompt,
            # v21.0.8: persist the full request body too so the
            # dashboard chat tab can lazy-fetch it on row expand
            # (the preview keeps the same 200-char cap).
            question_full=prompt,
            duration_ms=elapsed_ms,
        )
    except ImportError:
        pass
    except Exception:
        logger.exception("network_log error-mirror failed; swallowing")


def _dump_dir() -> Path:
    """Return the directory for truncated-output dumps.

    Uses $XDG_STATE_HOME (or ~/.local/state) by default, NOT /tmp — claude
    output may include private code, secrets, or SSH host data. Creates the
    directory mode 0o700 (owner-only) on first use.
    """
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    d = Path(state) / "harbormaster" / "dumps"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def run_backend(
    *,
    name: str,
    prompt: str,
    max_turns: int,
    host: str | None,
    config: HarbormasterConfig,
    label_prefix: str,
    model: str | None = None,
) -> str:
    """Dispatch a prompt to local or remote backend, return the (possibly
    truncated) result text or an 'Error: ...' string.

    No SSH glue here — that's encapsulated inside the backend. This function
    is purely orchestration: validate the project name, pick the backend,
    pick local-vs-remote, dispatch, and translate exceptions to strings at
    the MCP boundary.

    On successful completion, optionally writes the trajectory back to
    FleetQ Memory (when [fleetq] is enabled and write_trajectories is
    true). Writeback failures are logged but never propagate — the
    user's response is already in flight by the time we attempt it.
    """
    try:
        validate_project_name(name)
    except ValueError as e:
        return f"Error: {e}"

    backend = get_backend_for_project(config, name)
    if backend is None:
        return (
            f"Error: no enabled backend for project {name!r} "
            f"(default_backend={config.default_backend!r})"
        )
    cap = backend.cfg.output_word_cap

    start = time.monotonic()
    try:
        if is_remote(host):
            host_cfg = config.hosts.get(host)
            remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
            connect_timeout = host_cfg.connect_timeout if host_cfg else 10
            total_timeout = host_cfg.total_timeout if host_cfg else 120
            result = backend.ask_remote(
                host=host,
                remote_cwd=f"{remote_htdocs}/{name}",
                prompt=prompt,
                max_turns=max_turns,
                connect_timeout=connect_timeout,
                total_timeout=total_timeout,
                model=model,
            )
            label = f"{label_prefix}-{host}-{name}"
        else:
            try:
                cwd = resolve_project(name, config.projects, ignore_patterns=config.ignore.patterns)
            except ValueError as e:
                return f"Error: {e}"
            result = backend.ask_local(
                cwd=cwd, prompt=prompt, max_turns=max_turns, model=model,
            )
            label = f"{label_prefix}-{name}"
    except BackendError as e:
        # v21.0.7: surface debug info on backend failures.
        # Before this patch, the agent received "Error: <message>" with
        # no project name, no elapsed, no correlation id — and nothing
        # was logged or recorded for the operator to investigate. Now
        # we tag every failure with a short id, write a structured
        # WARNING log line, mirror it into the network_log so the
        # dashboard Activity tab shows it, and return a richer string
        # to the agent so it can pinpoint which call failed.
        cid = _new_correlation_id()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _record_backend_failure(
            project_name=name,
            host=host,
            prompt=prompt,
            tool=label_prefix,
            error=e,
            elapsed_ms=elapsed_ms,
            correlation_id=cid,
        )
        loc = host or "local"
        # NOTE: must start with the literal "Error:" — fan_out.py
        # filters target answers on this prefix, and external MCP
        # agents have historically pattern-matched on it too. The
        # correlation id and metadata live AFTER the colon.
        return (
            f"Error: {label_prefix}(name={name!r}, host={loc!r}) "
            f"failed after {elapsed_ms} ms [cid={cid}] "
            f"— code={e.code}: {e}"
        )

    _maybe_writeback_to_fleetq(
        config=config,
        project_name=name,
        host=host,
        prompt=prompt,
        answer=result.output,
        tool=label_prefix,
        duration_ms=result.duration_ms,
    )

    _maybe_record_qa(
        config=config,
        project_name=name,
        host=host,
        prompt=prompt,
        answer=result.output,
        tool=label_prefix,
        duration_ms=result.duration_ms,
    )

    _maybe_extract_and_writeback_kg(
        config=config,
        project_name=name,
        host=host,
        answer=result.output,
        tool=label_prefix,
    )

    return _truncate(result.output, cap, label)


def run_instruction(
    *,
    name: str,
    prompt: str,
    max_turns: int,
    host: str | None,
    config: HarbormasterConfig,
    label_prefix: str,
    model: str | None = None,
    allow_writes: bool = False,
    auto_commit: bool = False,
    deliverable: str = "",
    inbox_id: str = "default",
    task_text: str | None = None,
    orchestrator: str = "claude",
) -> str:
    """v26.0.0 — instruction-mode counterpart to ``run_backend``.

    Creates one ``delegated_jobs`` row with status ``awaiting_caller``
    and returns the markdown instruction packet. The calling MCP client
    is expected to execute the embedded prompt via its sub-agent primitive
    and then invoke ``record_delegation_result`` to transition the row to
    ``completed`` / ``failed``.

    No subprocess spawn, no LLM round-trip — this function completes in
    a single SQLite write plus string formatting.

    ``task_text`` (when provided) is what gets persisted in the row's
    ``task`` column for UI / recall surfaces. When None, the full
    ``prompt`` is used. Pass a short task description here for cleaner
    /jobs rendering.

    ``orchestrator`` (v27.0.0) selects the packet-rendering adapter
    (``claude`` / ``codex`` / ``gemini`` / ``neutral``). Must be a known
    adapter — callers resolve + validate it before reaching here. The
    name is persisted on the row so ``get_delegated_task`` rebuilds the
    packet with the same adapter.
    """
    try:
        validate_project_name(name)
    except ValueError as e:
        return f"Error: {e}"

    try:
        cwd = resolve_project(name, config.projects, ignore_patterns=config.ignore.patterns)
    except ValueError as e:
        return f"Error: {e}"

    # Late import to avoid a tools ↔ jobs import cycle at module load time.
    from harbormaster.jobs import get_subsystem
    from harbormaster.jobs.schema import STATUS_AWAITING_CALLER

    sub = get_subsystem(config)
    kind: PacketKind = (
        "ask" if label_prefix == "ask"
        else packet_kind_for_delegate(allow_writes, auto_commit)
    )

    job = sub.store.enqueue(
        project=name,
        host=host,
        task=task_text if task_text is not None else prompt,
        deliverable=deliverable,
        allow_writes=allow_writes,
        model=model,
        inbox_id=inbox_id,
        max_turns=max_turns,
        auto_commit=auto_commit,
        execution_mode="instruction",
        initial_status=STATUS_AWAITING_CALLER,
        # v26.0.0 — persist the rendered prompt so a caller that loses
        # the original packet response can recover it faithfully via
        # get_delegated_task. The recovered packet must carry the same
        # role suffix (read-only / writes / writes+auto-commit) as the
        # initial render — otherwise an allow_writes=False job's
        # recovered Agent could edit files.
        rendered_prompt=prompt,
        orchestrator=orchestrator,
    )

    packet = build_packet(
        job_id=job.id,
        kind=kind,
        project=name,
        cwd=str(cwd),
        host=host,
        prompt=prompt,
        max_turns=max_turns,
        model_hint=model,
        allow_writes=allow_writes,
        auto_commit=auto_commit,
    )
    adapter = get_adapter(orchestrator)
    # Defensive: callers resolve to a known adapter before reaching here.
    # If an unknown name slips through, fall back to the claude renderer
    # rather than crashing the tool call.
    if adapter is None:  # pragma: no cover - guarded upstream
        return packet.to_markdown()
    return adapter.render_packet(packet)


def run_backend_or_instruction(
    *,
    name: str,
    prompt: str,
    max_turns: int,
    host: str | None,
    config: HarbormasterConfig,
    label_prefix: str,
    model: str | None = None,
    allow_writes: bool = False,
    auto_commit: bool = False,
    deliverable: str = "",
    inbox_id: str = "default",
    task_text: str | None = None,
    orchestrator: str | None = None,
) -> str:
    """v26.0.0 — top-level dispatcher: instruction mode (default) or
    subprocess mode (legacy). Falls back to subprocess for SSH targets
    regardless of config because the calling assistant has no PTY to
    the remote host.

    Returns either an instruction packet (markdown with
    ``HARBORMASTER_INSTRUCTION_V1`` marker) or the v25 subprocess result
    string. Both shapes are accepted by all existing callers — the
    instruction-packet response is itself a markdown string.

    v27.0.0 — in instruction mode the effective orchestrator is resolved
    via ``resolve_orchestrator`` (explicit ``orchestrator`` param > config
    > MCP clientInfo auto-detect > ``claude`` default). If the resolved
    orchestrator has no adapter (an unknown name pinned by param/config),
    the call transparently falls back to subprocess execution — an
    unrecognised orchestrator can't run a packet.
    """
    mode = execution_mode_for(config, host)
    if mode == "instruction":
        orch = resolve_orchestrator(
            explicit=orchestrator,
            config=config,
            detected=detect_client_orchestrator(),
        )
        if get_adapter(orch) is not None:
            return run_instruction(
                name=name,
                prompt=prompt,
                max_turns=max_turns,
                host=host,
                config=config,
                label_prefix=label_prefix,
                model=model,
                allow_writes=allow_writes,
                auto_commit=auto_commit,
                deliverable=deliverable,
                inbox_id=inbox_id,
                task_text=task_text,
                orchestrator=orch,
            )
        logger.warning(
            "unknown orchestrator %r — falling back to subprocess for "
            "tool=%s project=%s",
            orch, label_prefix, name,
        )
    return run_backend(
        name=name,
        prompt=prompt,
        max_turns=max_turns,
        host=host,
        config=config,
        label_prefix=label_prefix,
        model=model,
    )


def _maybe_writeback_to_fleetq(
    *,
    config: HarbormasterConfig,
    project_name: str,
    host: str | None,
    prompt: str,
    answer: str,
    tool: str,
    duration_ms: int,
) -> None:
    """Best-effort POST of the trajectory to FleetQ /api/v1/memory.

    Skipped silently when:
      - [fleetq] is disabled
      - write_trajectories is false
      - the [fleetq] extra is not installed
      - the API token env var is empty

    Network / HTTP failures are logged at WARNING level but never
    propagate. This function is fire-and-forget from the caller's
    perspective — the MCP tool's response is already being prepared
    by the time we get here.
    """
    if not (config.fleetq.enabled and config.fleetq.write_trajectories):
        return

    api_token = os.environ.get(config.fleetq.api_token_env, "").strip()
    if not api_token:
        return

    try:
        from harbormaster.fleetq.memory import MemoryWriter
    except ImportError:
        return

    try:
        writer = MemoryWriter(
            base_url=config.fleetq.base_url,
            api_token=api_token,
        )
    except ValueError:
        return

    try:
        writer.write_trajectory(
            project_name=project_name,
            host=host,
            question=prompt,
            answer=answer,
            tool=tool,
            metadata={"duration_ms": duration_ms},
        )
    finally:
        writer.close()


def _maybe_extract_and_writeback_kg(
    *,
    config: HarbormasterConfig,
    project_name: str,
    host: str | None,
    answer: str,
    tool: str,
) -> None:
    """Best-effort heuristic triple extraction + POST to FleetQ KG.

    Skipped silently when:
      - [fleetq] is disabled
      - [fleetq] write_kg is false (default false; opt-in even when
        write_trajectories is true, since KG triples are noisier and
        operators may want trajectories without graph extraction)
      - the [fleetq] extra is not installed
      - the API token env var is empty
      - the answer is empty / too short to extract from

    Mirror of `_maybe_writeback_to_fleetq` — same fire-and-forget,
    same silent-on-failure semantics. Three triple types: mentions,
    uses, exposes (see harbormaster.fleetq.triples). Capped at
    [fleetq].kg_max_triples_per_call to bound writeback cost on dense
    answers.
    """
    if not (config.fleetq.enabled and config.fleetq.write_kg):
        return
    if not answer or len(answer.strip()) < 8:
        return

    api_token = os.environ.get(config.fleetq.api_token_env, "").strip()
    if not api_token:
        return

    try:
        from harbormaster.fleetq.kg import KGWriter
        from harbormaster.fleetq.triples import extract_all
    except ImportError:
        return

    # Cheap O(N) project-name lookup — discover_projects is cached at
    # the OS level (git log + serena stat) and runs fast on every call.
    try:
        from harbormaster.projects import discover_projects

        known_projects = [
            p.name for p in discover_projects(
                config.projects, ignore_patterns=config.ignore.patterns,
            )
        ]
    except Exception:
        logger.exception("kg: discover_projects failed; skipping mention extraction")
        known_projects = []

    from harbormaster.fleetq.kg import Triple

    extractor = config.fleetq.kg_extractor
    triples: list[Triple] = []
    # Heuristic path: cheap regex pass; runs for "heuristic" + "both".
    if extractor in ("heuristic", "both"):
        triples.extend(
            extract_all(
                answer=answer,
                source_project=project_name,
                known_projects=known_projects,
                max_triples=config.fleetq.kg_max_triples_per_call,
            )
        )
    # LLM path: one extra ask_local() call; runs for "llm" + "both".
    # Local-only — remote `host` skips LLM extraction entirely (the
    # SSH round trip per call is too expensive to justify in v2.0.0a5).
    if extractor in ("llm", "both") and not is_remote(host):
        try:
            from harbormaster.backends import get_backend_for_project
            from harbormaster.fleetq.triples_llm import extract_via_llm
        except ImportError:
            pass
        else:
            backend = get_backend_for_project(config, project_name)
            cwd: Path | None
            try:
                cwd = resolve_project(project_name, config.projects, ignore_patterns=config.ignore.patterns)
            except ValueError:
                cwd = None
                backend = None
            if backend is not None and cwd is not None:
                triples.extend(
                    extract_via_llm(
                        answer=answer,
                        source_project=project_name,
                        backend=backend,
                        cwd=cwd,
                        max_triples=config.fleetq.kg_llm_max_triples,
                    )
                )
    if not triples:
        return
    # Dedup by (subject, predicate, object) — keep highest-confidence
    # variant when the same triple is produced by both paths.
    deduped: dict[tuple[str, str, str], Triple] = {}
    for t in triples:
        key = (t.subject, t.predicate, t.obj)
        existing = deduped.get(key)
        if existing is None or t.confidence > existing.confidence:
            deduped[key] = t
    triples = list(deduped.values())[: config.fleetq.kg_max_triples_per_call]

    try:
        writer = KGWriter(
            base_url=config.fleetq.base_url,
            api_token=api_token,
        )
    except ValueError:
        return

    try:
        writer.write_triples(
            triples=triples,
            project_name=project_name,
            host=host,
            source_tool=tool,
        )
    finally:
        writer.close()


def _history_logging_enabled_for(config: HarbormasterConfig, tool: str) -> bool:
    """Per-tool gate. Each tool can opt out via [history] log_<tool> = false.
    Unknown tools default to enabled (matches "if history.enabled = true,
    log everything new")."""
    if not config.history.enabled:
        return False
    flag_name = f"log_{tool}"
    return bool(getattr(config.history, flag_name, True))


def _maybe_record_qa(
    *,
    config: HarbormasterConfig,
    project_name: str,
    host: str | None,
    prompt: str,
    answer: str,
    tool: str,
    duration_ms: int,
) -> None:
    """Best-effort write of the trajectory to the local sqlite Q&A
    history store. Mirrors _maybe_writeback_to_fleetq's three-gate
    pattern; the store opens the per-host db, inserts, and closes.

    Skipped silently when:
      - [history] is disabled
      - log_<tool> is false for this tool
      - the [history] extra is not installed (or fastembed import fails
        and we have not yet decided on FTS5 fallback)

    Failures inside the store (sqlite errors, embedding failures) are
    logged at WARNING level but never propagate. Same fire-and-forget
    semantics as the FleetQ writeback.
    """
    if not _history_logging_enabled_for(config, tool):
        return

    try:
        from harbormaster.history import (
            QARecord,
            QAStore,
            get_embedding_backend,
        )
    except ImportError:
        return

    try:
        backend = get_embedding_backend(config)
        store = QAStore.open(
            db_dir=config.history.db_dir,
            host=host,
            embedding_backend=backend,
            embedding_dim=config.history.embedding_dim,
        )
    except Exception:
        logger.exception("opening history store failed; skipping record")
        return

    try:
        store.record(
            QARecord(
                question=prompt,
                answer=answer,
                project=project_name,
                host=host or "local",
                tool=tool,
                duration_ms=duration_ms,
            )
        )
    except Exception:
        logger.exception("history record failed; swallowing")

    # v21.0.6: also mirror this call into the UI's network_log so the
    # dashboard Activity / Timeline tabs surface stdio-driven activity,
    # not just HTTP /mcp/{server} requests. Lazy import — when the [ui]
    # extra isn't installed (pure stdio MCP setup) the ImportError is
    # swallowed and we no-op, preserving the no-required-ui invariant.
    # Failures inside record() are also swallowed; logging mustn't
    # break the hot path.
    try:
        from harbormaster.ui.network_log import (
            current_caller_project,
            network_log,
        )

        network_log.record(
            caller=current_caller_project() or "operator",
            target=project_name,
            tool=tool,
            status="ok",
            question_preview=prompt,
            # v21.0.8: persist the full request body too so the
            # dashboard chat tab can lazy-fetch it on row expand
            # (the preview keeps the same 200-char cap).
            question_full=prompt,
            duration_ms=duration_ms,
        )
    except ImportError:
        pass
    except Exception:
        logger.exception("network_log mirror failed; swallowing")

    try:
        # v12.0.0a3: `[retention]` overrides the [history] caps
        # when set, so all retention knobs can live in one place.
        # Default `None` preserves the historical [history] values.
        recent_k = (
            config.retention.qa_log_recent_k
            if config.retention.qa_log_recent_k is not None
            else config.history.retain_recent_k
        )
        top_r = (
            config.retention.qa_log_top_recalled_r
            if config.retention.qa_log_top_recalled_r is not None
            else config.history.retain_top_recalled_r
        )
        store.prune(
            retain_recent_k=recent_k,
            retain_top_recalled_r=top_r,
        )
    except Exception:
        logger.exception("history prune failed; swallowing")
    store.close()


def make_local_backend_stream(
    *,
    project_name: str,
    prompt: str,
    max_turns: int,
    config: HarbormasterConfig,
    model: str | None = None,
) -> Iterator[str]:
    """Eagerly validate inputs and return the backend's streaming
    iterator against a local project.

    Tool-agnostic: callers (ask_project, delegate_task, future tools)
    are responsible for building the full prompt before invoking this.
    This function only worries about backend availability + project
    resolution, NOT tool-specific framing.

    Important: this function is **not** a generator function — `yield`
    appears nowhere in its body. That's deliberate: argument validation
    (project name, backend availability, project resolution) must run
    when the function is called, not lazily on the first `next()` of
    a returned generator. Lazy validation makes it impossible for the
    SSE dispatcher to distinguish "bad input → 400" from "subprocess
    died mid-stream → 502" because both errors bubble out of the same
    `next()` call site.

    Failure modes (raised eagerly — callers map to SSE error events):
      - ValueError       → invalid project name / project not found
      - BackendError     → backend disabled / streaming not supported
                           / subprocess failure (raised lazily on first
                           next() once iteration starts)
    """
    validate_project_name(project_name)
    backend = get_backend_for_project(config, project_name)
    if backend is None:
        raise BackendError(
            f"no enabled backend for project {project_name!r} "
            f"(default_backend={config.default_backend!r})",
            code="config_error",
        )
    if not hasattr(backend, "ask_local_stream"):
        raise BackendError(
            f"backend {backend.name!r} does not support streaming",
            code="config_error",
        )
    cwd = resolve_project(project_name, config.projects, ignore_patterns=config.ignore.patterns)
    stream: Iterator[str] = backend.ask_local_stream(
        cwd=cwd,
        prompt=prompt,
        max_turns=max_turns,
        model=model,
    )
    return stream


def make_remote_backend_stream(
    *,
    project_name: str,
    prompt: str,
    max_turns: int,
    host: str,
    config: HarbormasterConfig,
    model: str | None = None,
) -> Iterator[str]:
    """SSH counterpart to make_local_backend_stream — eagerly validates and
    returns the remote streaming iterator.

    Tool-agnostic: callers build the full prompt; this function only
    handles backend lookup and host-config resolution.

    Failure modes (raised eagerly):
      - ValueError      → invalid project name
      - BackendError    → backend disabled / streaming not supported
                          / SSH or remote-process failure (raised on
                          first next() once iteration begins)
    """
    validate_project_name(project_name)
    backend = get_backend_for_project(config, project_name)
    if backend is None:
        raise BackendError(
            f"no enabled backend for project {project_name!r} "
            f"(default_backend={config.default_backend!r})",
            code="config_error",
        )
    if not hasattr(backend, "ask_remote_stream"):
        raise BackendError(
            f"backend {backend.name!r} does not support remote streaming",
            code="config_error",
        )
    host_cfg = config.hosts.get(host)
    remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
    connect_timeout = host_cfg.connect_timeout if host_cfg else 10
    total_timeout = host_cfg.total_timeout if host_cfg else 120
    stream: Iterator[str] = backend.ask_remote_stream(
        host=host,
        remote_cwd=f"{remote_htdocs}/{project_name}",
        prompt=prompt,
        max_turns=max_turns,
        connect_timeout=connect_timeout,
        total_timeout=total_timeout,
        model=model,
    )
    return stream


def _truncate(text: str, word_cap: int, source_label: str) -> str:
    words = text.split()
    if len(words) <= word_cap:
        return text
    truncated = " ".join(words[:word_cap])
    try:
        dump_path = _dump_dir() / f"harbormaster-{source_label}-{int(time.time())}.md"
        dump_path.write_text(text, encoding="utf-8")
        os.chmod(dump_path, 0o600)
        return f"{truncated}\n\n[...truncated, full output: {dump_path}]"
    except OSError:
        return f"{truncated}\n\n[...truncated, dump failed]"
