# Anthropic Agent SDK Credit Policy — Impact on Harbormaster

**Date**: 2026-05-14
**Effective**: 2026-06-15
**Author**: Research synthesis via /sc:research
**Subject**: $200/mo Max 20x credit pool for Agent SDK + `claude -p`, and Harbormaster routing strategy

---

## Executive Summary

Starting **June 15, 2026**, all programmatic Claude usage (Agent SDK Python/TS, `claude -p`, Claude Code GitHub Actions, and third-party apps authenticating through Agent SDK — **Harbormaster falls in this last bucket**) is decoupled from the Max plan's interactive usage pool and instead drains a separate **$200/mo monthly credit** (Max 20x tier; $100 for Max 5x; $20 for Pro). Credits **do not roll over**, refresh monthly, are not pooled across users, and are billed at **full Claude API rates** under the hood — i.e. no subsidization. Once exhausted, requests block until next cycle unless "extra usage" (pay-as-you-go API billing) is manually enabled.

For Harbormaster's typical user (50–200 delegate calls/day) the $200 pool is **sufficient with optimization** (Haiku-default + `--bare` mode + existing QA recall cache) but **at risk of exhaustion** on a naive Sonnet-default workflow. Recommended action: switch backend to **Claude Agent SDK Python with `CLAUDE_CODE_OAUTH_TOKEN`** (preserving Claude Code features), introduce Haiku-default with Sonnet promotion for writes-allowed tasks, add `--bare` toggle, and keep Codex backend as a fallback when credit runs dry.

---

## 1. Verified Facts (Primary Sources)

### 1.1 What Counts as Programmatic vs Interactive

**Source**: [Anthropic Help Center — Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)

> **The credit applies to:**
> - Claude Agent SDK usage in your own projects (Python or TypeScript)
> - The `claude -p` command in Claude Code (non-interactive mode)
> - The Claude Code GitHub Actions integration
> - **Third-party apps that authenticate with your Claude subscription through the Agent SDK**
>
> **The credit doesn't apply to:**
> - Interactive Claude Code in the terminal or IDE
> - Claude conversations on the web, desktop, or mobile apps
> - Claude Cowork

**Harbormaster classification**: `BackendClaude.run()` shells out to `claude -p` → **falls in the programmatic bucket** → drains the $200 credit. Confirmed by inspection of `src/harbormaster/backends/claude.py`.

### 1.2 Credit Mechanics

**Source**: [Anthropic Help Center, op. cit.](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), corroborated by [The Decoder](https://the-decoder.com/claude-subscriptions-get-separate-budgets-for-programmatic-use-billed-at-full-api-prices/)

| Property | Value |
|---|---|
| Max 20x credit | **$200/mo** |
| Max 5x credit | $100/mo |
| Pro credit | $20/mo |
| Team Standard | $20/seat |
| Team Premium | $100/seat |
| Rollover | **No** — unused credit expires at billing cycle end |
| Pooling | **No** — per-user, not shared across teammates |
| Refresh | Auto, monthly |
| Opt-in | One-time claim per account |
| Drain order | Credit pool drains **first**, before extra usage |
| Past-credit | Falls back to "extra usage" at API rates, ONLY if manually enabled. Otherwise requests **block** until refresh |
| Billing rate | **Full Claude API rates** — no subscription subsidy |
| Activation email | June 8 from Anthropic, change goes live June 15 |

### 1.3 Authentication — Critical for Routing

**Source**: [Anthropic Docs — Authentication](https://code.claude.com/docs/en/authentication)

Claude Code/Agent SDK auth precedence (highest priority first):

1. Cloud provider creds (`CLAUDE_CODE_USE_BEDROCK`/`VERTEX`/`FOUNDRY`)
2. `ANTHROPIC_AUTH_TOKEN` — for LLM gateway/proxy bearer auth
3. **`ANTHROPIC_API_KEY`** — Console API key. **Always bills to API account at full API rates, never to subscription credit.** Takes precedence over OAuth.
4. `apiKeyHelper` script output
5. **`CLAUDE_CODE_OAUTH_TOKEN`** — long-lived OAuth token from `claude setup-token`. **Bills to subscription credit pool.**
6. Subscription OAuth from `/login` — Pro/Max default.

**The critical trap**: If `ANTHROPIC_API_KEY` is set in env, all `claude -p` and Agent SDK calls bill to API account, NOT credit. There's a documented incident ([GitHub #37686](https://github.com/anthropics/claude-code/issues/37686)) where a Max subscriber received **$1,800+ in API charges in two days** because cron-scheduled `claude -p` calls picked up the env var and routed to API billing.

> **Workflow to bill to subscription credit:**
> ```bash
> claude setup-token   # generates long-lived token, requires browser
> export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
> unset ANTHROPIC_API_KEY  # critical
> ```
> Then `claude -p` and `claude-agent-sdk` calls bill to the $200 pool.

### 1.4 API Pricing (Standard, Non-Batch, May 2026)

**Source**: [Anthropic API Docs — Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

| Model | Input ($/MTok) | Output ($/MTok) |
|---|---|---|
| Claude Opus 4.7 | $5.00 | $25.00 |
| Claude Sonnet 4.6 | $3.00 | $15.00 |
| **Claude Haiku 4.5** | **$1.00** | **$5.00** |

Batch API: 50% discount on the above (Sonnet 4.6 batch = $1.50/$7.50). **Batch is async with up to 24h SLA** — usable for non-realtime delegate tasks.

### 1.5 Prompt Caching — Massive Cost Lever

**Source**: [Anthropic API Docs — Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

| Cache op | Multiplier vs base input | Duration |
|---|---|---|
| 5-min cache write | 1.25× | 5 min |
| 1-hour cache write | 2× | 1 hour |
| **Cache read (hit)** | **0.1×** (= 10% of input price) | Same as write duration |

A cached system prompt + tool definitions reused across N calls cuts input cost to ~10% after first call. Available natively in Agent SDK and API.

### 1.6 Bare Mode — Token Reduction

**Source**: [Anthropic Docs — Headless](https://code.claude.com/docs/en/headless)

> Add `--bare` to reduce startup time by skipping auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md.

For Harbormaster delegates that only need core tools (Read/Edit/Bash), `--bare` cuts the initial context payload substantially — Anthropic doesn't publish exact token savings but auto-discovered hooks + skills + plugin manifests routinely contribute 5k–15k input tokens before the first user prompt.

### 1.7 Agent SDK Capabilities

**Source**: [Agent SDK Overview](https://code.claude.com/docs/en/agent-sdk/overview), [OAuth Demo Repo](https://github.com/weidwonder/claude_agent_sdk_oauth_demo), [Dev.to community guide](https://dev.to/aviv_shaked/how-to-use-your-claude-promax-subscription-with-the-agent-sdk-python-typescript-4emi)

- Same agent loop, tools, context management as Claude Code interactive
- Loads `.claude/` from cwd and `~/.claude/` by default (CLAUDE.md auto-load works)
- Session resume via `session_id` (durable JSONL on local filesystem)
- Custom tools as in-process Python functions
- Supports MCP servers, skills, hooks, plugins
- Python: `from claude_agent_sdk import query, ClaudeAgentOptions`
- Authenticates via OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) OR API key — same auth chain as CLI
- **Third-party-apps caveat** from official docs: *"Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products."* This means you can't distribute a binary that **logs other users into their Claude account**, but **personal use of your OWN OAuth token from `claude setup-token` is the sanctioned path** for self-hosted automation.

### 1.8 OpenAI Codex CLI — Competitive Reference

**Sources**: [Codex CLI](https://developers.openai.com/codex/cli), [Codex Pricing](https://developers.openai.com/codex/pricing)

- `codex` CLI: `npm i -g @openai/codex`
- Auth via ChatGPT account OR API key (same dual-mode as Claude)
- **Included** in ChatGPT Plus ($20), Pro ($200), Business/Edu/Enterprise — no separate Codex subscription
- 5-hour rolling window usage caps; Pro = 20× Plus baseline (was 25× promo through May 31, 2026)
- Feature parity with Claude Code: tools, MCP, AGENTS.md (= CLAUDE.md analog), skills, subagents, hooks
- **Implication**: A ChatGPT Pro subscription ($200/mo) gives Codex CLI access with NO credit pool gating — soft/hard caps on rolling 5h windows but no monthly hard ceiling like Anthropic's $200 credit. Different shape — useful as a fallback.

### 1.9 Real-World Credit Capacity Estimates

**Source**: [explainx.ai analysis](https://explainx.ai/blog/claude-programmatic-usage-credits-2026)

| Plan | Credit | Sonnet token ROI | Practical use case |
|---|---|---|---|
| Pro | $20 | ~1.5M–2M tokens | Individual coding, ~200 PR reviews/mo |
| Max 5x | $100 | ~7M–10M tokens | Small team orchestration |
| **Max 20x** | **$200** | **~15M–20M tokens** | Heavy R&D, continuous automated testing |

Anchored on **Sonnet ~$3/$15** standard pricing (50/50 input/output mix → ~$9/MTok blended → 20M tokens for $200; if biased to input via heavy CLAUDE.md/MCP context, → 65M tokens).

Anchored on **Haiku 4.5 $1/$5**: ~3× cheaper than Sonnet → ~$200 buys 60–200M tokens equivalent.

---

## 2. Harbormaster-Specific Cost Model

### 2.1 Current Per-Call Profile (v25.0.0, `claude -p` subprocess)

Per `delegate_task` / `ask_project` call to `BackendClaude`:

| Component | Approx tokens (input) |
|---|---|
| System prompt (Claude Code default) | ~6,000 |
| Auto-loaded CLAUDE.md (project-level) | ~2,000–8,000 |
| Auto-loaded Serena memories | ~5,000–15,000 |
| MCP server manifests + tool definitions | ~3,000–10,000 |
| Skills + hooks + plugins auto-discovered | ~5,000–15,000 |
| User task prompt + grounding | ~500–3,000 |
| **Total input (warm context)** | **~20k–55k** |
| Tool-use turns (≤10 by default) | output: 5k–20k |
| **Total output** | **~5k–20k** |

Per-call cost at standard Sonnet 4.6 (no caching):

- Median: 35k input × $3/MTok + 10k output × $15/MTok = **$0.105 + $0.15 = $0.255/call**
- Heavy: 55k × $3 + 20k × $15 = $0.165 + $0.30 = **$0.465/call**

### 2.2 Projected Monthly Burn (Max 20x, $200 credit)

| Workload | Per-call | Calls/mo @ $200 |
|---|---|---|
| Sonnet 4.6, no caching, full context | $0.25–$0.47 | **425–800 calls** |
| Sonnet 4.6, `--bare` mode | ~$0.15 | **~1,300 calls** |
| Sonnet 4.6, `--bare` + prompt caching (90% hit) | ~$0.06 | **~3,300 calls** |
| **Haiku 4.5, `--bare` + caching** | **~$0.02** | **~10,000 calls** |

User profile (50–200 delegates/day = 1.5k–6k/mo):
- **Naive Sonnet**: exhausts credit in **3–13 days**. ⚠️
- **`--bare` + caching Sonnet**: comfortable headroom (~50%–200% of credit).
- **Haiku-default + Sonnet-promote**: very comfortable (~15%–60% of credit).

---

## 3. Architectural Options (Ranked by Cost/Effort Tradeoff)

### Option A — **Recommended**: Agent SDK + OAuth + Haiku-default + bare mode

**Effort**: Medium (~1 sprint, ~v26.0.0)
**Cost impact**: Brings projected user inside the $200 credit envelope with 2–10× headroom.
**Risk**: Low.

Concrete changes to `src/harbormaster/backends/claude.py`:
1. Replace `subprocess.run(["claude", "-p", ...])` with `claude_agent_sdk.query()` in-process Python calls. Removes ~1s Node startup per call, removes subprocess pipe overhead.
2. Auth contract: require `CLAUDE_CODE_OAUTH_TOKEN` env var; **fail loudly** with a helpful error if `ANTHROPIC_API_KEY` is set (to prevent the $1,800 trap). Add a `harbormaster doctor` check.
3. New config knob `[backends.claude] default_model = "haiku-4.5"` (currently sonnet) with `model_aliases` already present per v21.0.0a10.
4. New config knob `[backends.claude] mode = "bare" | "full"` — passes `--bare` / `setting_sources=[]` for delegates that don't need MCP/skills/hooks. Default `"bare"` for read-only `ask_project`; `"full"` only when delegate task explicitly requires plugins.
5. Promote to Sonnet for: `allow_writes=True`, `auto_commit=True`, or complex multi-tool tasks (max_turns ≥ 5).
6. Enable Agent SDK session caching: persist `session_id` per (project, task-hash) so multi-turn delegates re-use cached context.
7. Wire prompt-caching `cache_control` on the system prompt + CLAUDE.md block — applies on second call within the 5-min/1-hour window.

Tradeoffs:
- **Pro**: cleanest architecture, future-proof against Anthropic CLI internals changes, in-process is faster, native session resume, Claude Code features (CLAUDE.md, MCP, skills) all still work.
- **Con**: SDK-binding adds a dependency on `claude-agent-sdk-python` (currently 6.9k stars on GitHub, actively maintained by Anthropic). v0.x semver — minor breakage risk.
- **Con**: must educate operators on `claude setup-token` step and the `ANTHROPIC_API_KEY` trap.

### Option B — Minimum-Effort: Stay on `claude -p` subprocess + force OAuth + add `--bare`

**Effort**: Small (~v25.1.0, hours of work)
**Cost impact**: ~40% savings vs naive — likely sufficient for moderate users.
**Risk**: Very low.

1. Keep subprocess `claude -p` calls in `backends/claude.py`.
2. Add `--bare` to default args; expose as config knob.
3. Add env-var guard: `harbormaster-mcp` startup logs warning if `ANTHROPIC_API_KEY` is set without `CLAUDE_CODE_OAUTH_TOKEN`.
4. Surface `default_model` UI affordance to make Haiku-default a one-click setting.
5. Document the `claude setup-token` flow in operator-config-reference.md.

Tradeoffs:
- **Pro**: zero new dependencies, minimal diff, ships in days.
- **Con**: still subprocess overhead. Misses native session resume and per-call prompt-caching control (CLI handles caching opaquely, you can't be sure of hit rate).

### Option C — Hybrid Backend Routing with Codex Fallback

**Effort**: Medium (~v26.x feature work, builds on A or B)
**Cost impact**: Eliminates the hard ceiling — when Claude credit runs out, work continues on ChatGPT.
**Risk**: Medium — operator must hold both subscriptions; cross-LLM consistency caveats.

1. Add config `[delegate] fallback_backend = "codex"` and `fallback_trigger = "credit_exhausted"`.
2. On Agent SDK return with "insufficient credit" error → automatically retry on `backends/codex.py` which already exists in v24.
3. Both backends emit the same `Backend.Result` shape so `JobStore` doesn't care.
4. UI shows which backend served each delegate (`delegated_jobs.backend` column).

Tradeoffs:
- **Pro**: graceful degradation. Operator gets full month of agent work even on heavy use.
- **Con**: Codex behaves differently — CLAUDE.md isn't read (AGENTS.md is); MCP servers connect identically but configured separately. Cross-backend test parity = real work.
- **Con**: Codex is also evolving its billing model. April 2, 2026 OpenAI moved from per-message to token-based; need ongoing monitoring.

### Option D — **Not Recommended**: PTY-driven interactive `claude` session

**Effort**: Small to medium (pexpect-based)
**Cost impact**: Routes through interactive subscription pool — appears "free" within Max plan limits.
**Risk**: **HIGH — likely against the spirit of the policy and fragile.**

Driving an interactive `claude` TUI via pexpect/ptyprocess to capture output and inject prompts.

Why we don't recommend it:
- Anthropic's policy distinction is enforced at the **transport layer** (how Claude Code identifies itself when calling the API). Reverse-engineering the interactive surface to drain interactive limits is the exact pattern Anthropic restructured the policy to prevent ("third-party tools like Conductor and OpenClaw started tapping into the Agent SDK, heavy usage burned through" → policy change).
- Anthropic has shown willingness to flag accounts for this pattern (April 2026 OpenClaw block).
- State pollution between tasks, error recovery hell, parallelism nightmare.
- One detection update from Anthropic and the entire pipeline breaks silently.

Mention only for completeness — actively recommend against.

### Option E — Self-Hosted / Local LLM Backend

**Effort**: Large
**Cost impact**: Zero per-call, requires hardware
**Risk**: Quality drop is real for agent workloads

Add `backends/ollama.py` or `backends/llama_cpp.py` using `qwen2.5-coder-32b` / `deepseek-coder-v2` / similar OSS models. Run on workstation GPU.

Tradeoffs:
- **Pro**: zero marginal cost.
- **Con**: tool-use quality on local models is still meaningfully below Claude/GPT for complex multi-turn delegates. Investment doesn't pay back unless you're running thousands of delegates/day with simple tasks.
- **Plausible niche**: `ask_project` read-only Q&A on local model, writes-allowed on Claude. Worth piloting **after** Options A+B+C ship.

---

## 4. Non-Obvious Findings

1. **`ANTHROPIC_API_KEY` env trap is the biggest operator footgun.** Set in `.zshrc` or inherited from a parent process, it silently routes everything to the pay-as-you-go API account. The $1,800/2-day incident is real. Harbormaster MUST log a startup warning if both vars are present, and the docs MUST front-load this.

2. **Prompt caching pays off in 1 call** at 5-min TTL (1.25× write, 0.1× hit) — for any system-prompt-stable workload, caching is essentially free money. Agent SDK supports `cache_control` natively. The legacy `claude -p` subprocess uses caching opaquely and you can't measure hit rate.

3. **Batch API (50% discount) is usable for async delegates.** Harbormaster's v22+ async delegate path with `mode="async"` could route through Batch API for non-time-critical jobs — gets a structural 2× cost reduction. SLA is up to 24h but most jobs complete in minutes.

4. **Per-user not pooled** means the Bridge / FleetQ multi-tenant model can't share credit. Each operator needs their own Max 20x. This is fine for FleetQ's per-team-per-operator architecture but kills any "shared agent" daydream.

5. **Claude Mythos Preview + Opus 4.7 + Sonnet 4.6 include 1M context at standard pricing** — no surcharge for long context. Removes one cost pressure but doesn't reduce the per-token rate.

6. **OpenAI Codex's "5-hour rolling window" model is structurally different.** It's not a monthly credit; it's a usage cap with reset. For bursty Harbormaster workloads (e.g. retro processing 200 projects in an hour) Anthropic's monthly model is friendlier; for steady continuous use, Codex's rolling caps may exhaust before month-end on heavy days.

7. **The `--continue` and `--resume` flags + Agent SDK session resume mean Harbormaster could batch multi-turn delegates into longer sessions** to amortize CLAUDE.md/MCP context across more output tokens. Today each delegate is a fresh process — significant waste.

---

## 5. Recommendation

Adopt **Option A (Agent SDK + OAuth + Haiku-default + bare mode)** as v26.0.0 sprint goal, with the **Option B subset shipping as v25.1.0** in the next ~3 days as a holding fix.

| Phase | Version | Goal | ETA |
|---|---|---|---|
| Stop the bleeding | v25.1.0 | `--bare` default + `default_model = "haiku-4.5"` + env-var guard + docs | 3–5 days |
| Architecture pivot | v26.0.0 | Replace subprocess with `claude-agent-sdk` Python; OAuth-only by default; prompt caching wired in; session resume | 2–3 weeks |
| Resilience | v26.1.0 | Codex fallback when credit exhausted; per-job backend tracking | 1–2 weeks after v26.0.0 |
| Long-tail | v27+ | Optional local-LLM backend for read-only `ask_project` Q&A | Pilot Q3 |

This roadmap keeps the typical operator inside the $200 credit envelope, gives a graceful degradation path, and aligns Harbormaster's billing surface with Anthropic's stated architecture rather than fighting it.

---

## Sources

- [Anthropic Help — Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Anthropic Help — Use Claude Code with your Pro or Max plan](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
- [Anthropic Docs — Agent SDK Overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Anthropic Docs — Run Claude Code Programmatically (Headless)](https://code.claude.com/docs/en/headless)
- [Anthropic Docs — Authentication](https://code.claude.com/docs/en/authentication)
- [Anthropic Docs — CLI Reference](https://code.claude.com/docs/en/cli-reference)
- [Anthropic API Docs — Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [The Decoder — Claude subscriptions get separate budgets for programmatic use](https://the-decoder.com/claude-subscriptions-get-separate-budgets-for-programmatic-use-billed-at-full-api-prices/)
- [XDA Developers — Anthropic's Claude subscriptions no longer include Agent SDK and claude -p usage](https://www.xda-developers.com/anthropics-claude-subscriptions-no-longer-include-agent-sdk-and-claude-p-usage/)
- [VentureBeat — Anthropic reinstates OpenClaw and third-party agent usage on Claude subscriptions — with a catch](https://venturebeat.com/technology/anthropic-reinstates-openclaw-and-third-party-agent-usage-on-claude-subscriptions-with-a-catch)
- [explainx.ai — The Claude Token Economy: Programmatic Credits 2026](https://explainx.ai/blog/claude-programmatic-usage-credits-2026)
- [GitHub Issue — Agent SDK should support Max plan billing (#559)](https://github.com/anthropics/claude-agent-sdk-python/issues/559)
- [GitHub Issue — claude -p with OAuth bills as API usage, not Max subscription (#43333)](https://github.com/anthropics/claude-code/issues/43333)
- [GitHub Issue — claude -p suggested to Max subscriber caused $1,800+ unintended API billing (#37686)](https://github.com/anthropics/claude-code/issues/37686)
- [Dev.to — How to use your Claude Pro/Max subscription with the Agent SDK (Python + TypeScript)](https://dev.to/aviv_shaked/how-to-use-your-claude-promax-subscription-with-the-agent-sdk-python-typescript-4emi)
- [GitHub — claude_agent_sdk_oauth_demo (community reference)](https://github.com/weidwonder/claude_agent_sdk_oauth_demo)
- [OpenAI Developers — Codex CLI](https://developers.openai.com/codex/cli)
- [OpenAI Developers — Codex Pricing](https://developers.openai.com/codex/pricing)
