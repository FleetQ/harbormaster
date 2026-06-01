# Requirements — Provider-Agnostic Orchestrator (instruction mode)

**Status**: Requirements discovery (brainstorm output). NOT a design or implementation plan.
**Date**: 2026-06-01
**Baseline**: v26.0.1 (instruction-mode default; Claude-Code-coupled orchestrator)
**Next step**: `/sc:design` for architecture, then `/sc:workflow` for build plan.

---

## 1. Problem statement

In v26 the default `[delegate] execution_mode = "instruction"` returns a markdown
packet (`HARBORMASTER_INSTRUCTION_V1`) that the **calling MCP client** must execute
by spawning an `Agent` / `Task` sub-agent. The packet is coupled to Claude Code:
it literally says *"call your `Agent` (or `Task`) tool"* and embeds
`subagent_type: "general-purpose"`. Any non-Claude MCP client sees the packet only
as human-readable text and cannot auto-execute it.

The **target / executing** side is already provider-agnostic (the `Backend` Protocol
ships `ClaudeBackend` + `CodexBackend`; `subprocess` mode works cross-provider). The
gap is on the **orchestrator / calling** side.

## 2. Goal (confirmed)

**Broader MCP client compatibility.** Let non-Claude MCP clients (Codex CLI, Gemini
CLI, generic MCP clients) automatically consume and execute an instruction packet,
so harbormaster does not have to spawn processes server-side for them. Focus is
**contract portability**, not billing-pool routing.

> Explicit non-goal: billing parity. The v26 billing rationale (sub-agent inherits
> the orchestrator's subscription auth) is Claude/Anthropic-specific. For other
> orchestrators the billing behaviour is whatever that vendor does; this work does
> not try to replicate or guarantee it. (See Open Question OQ-5.)

## 3. Scope decisions (confirmed during brainstorm)

| Decision | Choice |
|---|---|
| Primary value | Broader MCP client compatibility (orchestrator side) |
| Target orchestrators | OpenAI Codex CLI · Gemini CLI · generic MCP clients |
| Packet contract form | Per-orchestrator adapters (render per declared client type) |
| Orchestrator identification | Hybrid resolution chain (tool param > config > clientInfo auto-detect > neutral default) |
| Unknown / no sub-agent capability | Auto fallback to `subprocess` (transparent) |
| Adapter extensibility | Built-in adapters now; design leaves room for a plugin registry later (no later refactor) |

## 4. Functional requirements

- **FR-1 — Orchestrator resolution.** A single resolver determines the effective
  orchestrator for a (call, config, session) tuple, using this precedence:
  1. explicit tool parameter `orchestrator` on `ask_project` / `delegate_task` / `fan_out_ask`
  2. `[delegate] orchestrator` config value
  3. MCP `initialize` `clientInfo.name` auto-detect (mapped to a known adapter)
  4. neutral default
  The resolver is the single source of truth, mirroring how `execution_mode_for`
  centralises the SSH-forces-subprocess rule.

- **FR-2 — Per-orchestrator packet rendering.** Given a resolved orchestrator, the
  instruction packet is rendered by the matching adapter:
  - `claude` — current v26 packet (Agent/Task, `subagent_type`), unchanged.
  - `codex` — Codex CLI's sub-agent invocation shape.
  - `gemini` — Gemini CLI's sub-agent invocation shape.
  - `neutral` — provider-neutral instructions ("spawn a sub-agent with this prompt")
    plus a machine-readable JSON descriptor, no Claude-specific tool names.
  - **Constraint (from OQ-1 validation):** Codex/Gemini have **no per-delegation
    `cwd` argument** — they delegate within the CLI's workspace. Non-Claude packets
    must therefore embed the project path **in the prompt body** ("operate on the
    project at `<path>`") rather than relying on a structured `cwd` field, or assume
    the orchestrator runs in the project directory. The `claude` adapter keeps the
    structured cwd it already uses.

- **FR-3 — Capability-aware fallback.** When the resolved orchestrator is unknown,
  or is known to lack a sub-agent primitive, the tool transparently falls back to
  `subprocess` execution and returns a finished result instead of a packet. SSH
  continues to force `subprocess` regardless (existing rule, unchanged).

- **FR-4 — Universal report-back.** All orchestrators report results via the
  existing `record_delegation_result` MCP tool (already provider-neutral). No new
  report-back channel is required for the confirmed targets.

- **FR-5 — Fan-out adapter awareness.** `fan_out_ask` instruction packets are
  rendered through the same adapter selection, so a non-Claude orchestrator gets a
  fan-out packet it can execute (N sub-agents in its own idiom). `batch_id`
  correlation (v26.0.1) is preserved.

- **FR-6 — Packet recovery fidelity.** `get_delegated_task` rehydrates an
  `awaiting_caller` packet using the **same adapter** that produced it. The chosen
  orchestrator/adapter must be recoverable for a row (alongside the existing
  persisted `rendered_prompt`).

- **FR-7 — Backward compatibility.** When the orchestrator resolves to `claude`,
  the emitted packet and behaviour are byte-for-byte the v26.0.1 packet. Existing
  Claude Code callers see zero change.

- **FR-8 — Observability.** The resolved orchestrator is visible per job (e.g. a
  `/jobs` column / detail field), the same way `Mode` and `Tokens` were added in
  v26.0.1.

## 5. Non-functional requirements

- **NFR-1** — `mypy --strict` clean and `ruff` clean (both gates run on every PR).
- **NFR-2** — Tests mirror source paths; every new behaviour gets unit coverage;
  integration fixtures that assume Claude must pin the orchestrator explicitly.
- **NFR-3** — No new core dependencies. Core stays `mcp` + `pydantic`; any
  per-orchestrator concern is contained, not leaked into core.
- **NFR-4** — Zero breaking changes within the GA line. New behaviour is
  default-safe: an upgrade with no config change and a Claude caller behaves like
  v26.0.1.
- **NFR-5** — Decision provenance: orchestrator resolution lives in ONE function;
  every dispatch point (ask, delegate sync/async, fan-out all-local gate) goes
  through it.
- **NFR-6** — Adapter layer is structured so a future plugin registry can register
  adapters at runtime (mirror of the planned backend plugin registry) without
  refactoring the call sites.

## 6. User stories / acceptance criteria

- **US-1 (Codex orchestrator).** *As a Codex CLI user who has added harbormaster as
  an MCP server, when I delegate a task, I receive a packet my CLI can execute
  natively and the result is recorded.*
  - AC: `delegate_task` with Codex resolved → packet uses Codex's sub-agent idiom,
    no `Agent`/`Task`/`subagent_type` Claude-isms.
  - AC: row enters `awaiting_caller`; `record_delegation_result` transitions it to
    `completed`/`failed` exactly as for Claude.

- **US-2 (Gemini orchestrator).** Same as US-1 for Gemini CLI.

- **US-3 (generic / unknown client).** *As a generic MCP client with no sub-agent
  primitive, when I delegate, I get a finished answer, not a packet I can't run.*
  - AC: unknown orchestrator → transparent `subprocess` execution → finished result.
  - AC: no `awaiting_caller` orphan is left behind.

- **US-4 (explicit override).** *As any caller I can force the adapter via
  `orchestrator=` regardless of clientInfo.*
  - AC: tool param wins over config and clientInfo.

- **US-5 (Claude unchanged).** *As an existing Claude Code user I see no difference.*
  - AC: resolved orchestrator `claude` → v26.0.1 packet byte-for-byte; existing
    v26 tests pass unmodified.

- **US-6 (operator visibility).** *As an operator I can see which orchestrator each
  delegated job used.*
  - AC: orchestrator surfaced on `/jobs` (column or detail panel).

## 7. Out of scope (this iteration)

- Billing-pool parity / guarantees for non-Claude orchestrators (OQ-5).
- Third-party plugin-registered adapters (design must *allow* it; shipping it is later).
- Any change to the executing/target `Backend` layer — it is already provider-agnostic.
- A non-MCP report-back transport (HTTP callback, webhook) — `record_delegation_result` suffices.
- Cross-tenant inbox isolation, relay-binary, Tauri/Electron — unchanged out-of-scope per architecture memory.

## 8. Open questions (must resolve before / during design)

- **OQ-1 (CRITICAL feasibility) — ✅ VALIDATED POSITIVE (2026-06-01).** Both CLIs
  ship first-class subagent delegation where the orchestrator LLM spawns a sub-agent
  with an **arbitrary task prompt**, the sub-agent runs in an isolated context with
  tool/MCP access, and returns a result to the parent. The instruction-mode premise
  holds for both. Evidence:
  - **Gemini CLI**: subagents are "exposed to the main agent **as a tool** … the
    main agent calls the tool [and] delegates the task … reports back." Built-in
    `generalist` agent "uses the inherited tool access … executing broad subtasks
    in an isolated conversation, returning only the final result" — the direct
    analog of Claude's `general-purpose` Agent. Subagents can access MCP tools
    (`mcp_*` wildcard / inline `mcpServers`).
  - **Codex CLI**: "Codex handles orchestration across agents, including spawning
    new subagents, routing follow-up instructions, waiting for results." Delegation
    is prompt-driven ("Spawn one agent per point, wait for all, summarize").
    Experimental `spawn_agents_on_csv` (with `instruction` template + per-worker
    `report_agent_job_result`) is a near-exact structural analog of harbormaster's
    `fan_out_ask` + `record_delegation_result`.
  - **Refinements this surfaced** (fold into design):
    - **No per-delegation `cwd` parameter** in either CLI (unlike Claude's Agent).
      Both operate in the CLI's workspace/sandbox. → FR-2 packets for non-Claude
      must convey the project path **inside the prompt** ("operate on the project
      at `<path>`"), not as a structured `cwd` arg, OR assume the orchestrator was
      launched in the project dir. See updated FR-2.
    - Delegation is **LLM-mediated** (the orchestrator model reads instructions and
      decides to spawn) — exactly like today's Claude markdown packet. So a
      "per-orchestrator adapter" is mostly **idiom/wording tuning** (`@generalist`
      for Gemini, "spawn an agent" for Codex), not a different transport. This
      simplifies the design and confirms the markdown-packet approach generalizes.
    - Both CLIs have their **own** internal report mechanisms (Codex
      `report_agent_job_result`). The neutral packet must be explicit that the
      parent calls **harbormaster's** `record_delegation_result`, to avoid the
      orchestrator closing the loop only internally.
    - Codex `agents.max_depth` defaults to `1` (a root session spawns children but
      no deeper). Fine for single-level delegation; note for fan-out-of-fan-out.
- **OQ-2.** Does the Python MCP SDK expose `clientInfo` (from `initialize`) at
  tool-call time so FR-1's auto-detect tier is implementable? If not, the chain
  degrades to param > config > neutral default.
- **OQ-3.** Is there any standard MCP mechanism for a client to declare
  `can_spawn_subagent`, or must FR-3 rely on harbormaster's own known-orchestrator
  allowlist (capability inferred from identity)?
- **OQ-4.** Do Codex/Gemini orchestrators reliably know to call
  `record_delegation_result` after executing the packet, or does the neutral packet
  need stronger, idiom-specific instructions to close the loop?
- **OQ-5.** Document (not solve) the billing implication for each non-Claude
  orchestrator so operators are not surprised: instruction mode here is about
  compatibility, not pool routing.
- **OQ-6.** What `clientInfo.name` strings do Codex CLI, Gemini CLI, Cursor, Cline
  actually report? FR-1 tier 3 needs an empirical mapping table.
- **OQ-7 (NEW).** Does Antigravity CLI (Gemini CLI's successor from 2026-06-18)
  preserve the same subagent-as-a-tool delegation contract? If yes, one
  "Gemini-family" adapter covers both; if not, prefer the neutral adapter for that
  family until the contract settles. See R-1b.

## 9. Risks

- **R-1.** ~~OQ-1 resolves negative~~ — **RETIRED**: OQ-1 validated positive for
  both Codex and Gemini (2026-06-01). Feature premise stands.
- **R-1b (NEW — Gemini sunset).** The Gemini CLI docs carry a banner: *"Unpaid tier
  and Google One users: Gemini CLI will be replaced by **Antigravity CLI** on June
  18th."* Targeting "Gemini CLI" by name is a moving target — the successor is
  Antigravity CLI (17 days out as of 2026-06-01). Mitigation: treat the Gemini
  adapter as "Gemini-family / Antigravity" and verify the subagent contract carries
  over before investing; the neutral adapter covers it regardless. **New OQ-7.**
- **R-2.** Per-orchestrator adapters drift as each CLI changes its sub-agent API →
  ongoing maintenance surface. Mitigation: keep adapters thin; centralise via FR-1
  resolver; lean on the planned plugin path (NFR-6) to externalise volatility later.
- **R-3.** clientInfo unreliability (OQ-2/OQ-6) makes auto-detect a foot-gun →
  silent wrong-adapter selection. Mitigation: param/config override always wins;
  unknown → safe subprocess fallback (FR-3), never a broken packet.
