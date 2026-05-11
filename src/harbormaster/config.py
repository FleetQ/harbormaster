"""TOML config loader.

Search order:
  1. ./.harbormaster.toml in cwd (per-project override)
  2. $XDG_CONFIG_HOME/harbormaster/config.toml (or ~/.config/harbormaster/config.toml)

If no config file is found, a HarbormasterConfig with defaults is returned —
the package is designed to be zero-config friendly when ~/htdocs/* exists.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LogLevel = Literal["debug", "info", "warning", "error", "critical"]
_FORBID_EXTRA = ConfigDict(extra="forbid")


class ProjectsConfig(BaseModel):
    model_config = _FORBID_EXTRA

    glob: list[str] = Field(default_factory=lambda: ["~/htdocs/*"])
    exclude: list[str] = Field(default_factory=list)
    require_marker: bool = False


class BackendConfig(BaseModel):
    model_config = _FORBID_EXTRA

    enabled: bool = True
    binary: str = "claude"
    extra_args: list[str] = Field(default_factory=lambda: ["-p"])
    timeout_local: int = Field(default=60, gt=0)
    timeout_remote: int = Field(default=120, gt=0)
    output_word_cap: int = Field(default=800, gt=0)


class HostProjectBudget(BaseModel):
    """v16.0.0a5: per-host-per-project budget cell.

    Lets an operator say "alpha host's frontend project may consume
    at most 50 ask-or-delegate calls per 24h" via TOML::

        [hosts.alpha.projects.frontend]
        daily_call_budget = 50

    Tightest cap wins when the per-host budget
    (``HostConfig.daily_call_budget``), the per-tool budget
    (``BudgetConfig.daily_call_budget_per_tool``) and this per-project
    budget all apply to the same call. ``None`` = no budget tracked.
    """

    model_config = _FORBID_EXTRA
    daily_call_budget: int | None = Field(default=None, gt=0)


class HostConfig(BaseModel):
    model_config = _FORBID_EXTRA

    ssh_host: str
    remote_htdocs: str = "~/htdocs"
    backend: str = "claude"
    connect_timeout: int = Field(default=10, gt=0)
    total_timeout: int = Field(default=120, gt=0)
    # v14.0.0a4: optional soft budget — MCP calls routed TO this host
    # per 24h. Surfaced via GET /api/hosts/budget which counts events
    # in network_log targeting this host vs the cap. None = no budget
    # tracked (host appears with budget=null in the report).
    daily_call_budget: int | None = Field(default=None, gt=0)
    # v16.0.0a5: per-project budget cells (carry-over #9). Closes the
    # third axis of the budget triad — per-host (this file),
    # per-tool ([budget].daily_call_budget_per_tool), per-project
    # (here). Surfaced via GET /api/projects/budget?host=<name>.
    projects: dict[str, HostProjectBudget] = Field(default_factory=dict)


class ServerConfig(BaseModel):
    model_config = _FORBID_EXTRA

    ui_port: int = Field(default=7531, gt=0, lt=65536)
    mcp_http_port: int = Field(default=7532, gt=0, lt=65536)
    log_level: LogLevel = "info"
    trajectory_retention_days: int = Field(default=90, gt=0)

    # v11.0.0a7: per-surface SSE heartbeat tuning. Each value is the
    # idle-second budget before a heartbeat frame is emitted. Different
    # surfaces have different needs:
    #   - streaming (ask/delegate/fan-out) — keep 5s; proxy-keepalive
    #     critical for long claude-p invocations.
    #   - network feed — 30s; events are infrequent, frequent
    #     heartbeats are pure noise.
    #   - dispatcher trace — 10s; mid-frequency.
    # Override via [server] heartbeat_interval_<surface>_s = <float>
    # in harbormaster.toml.
    heartbeat_interval_streaming_s: float = Field(default=5.0, gt=0)
    heartbeat_interval_network_s: float = Field(default=30.0, gt=0)
    heartbeat_interval_trace_s: float = Field(default=10.0, gt=0)


class StorageConfig(BaseModel):
    model_config = _FORBID_EXTRA

    db_path: str = "~/.local/share/harbormaster/harbormaster.db"
    enable_dedup: bool = False


class FleetQConfig(BaseModel):
    model_config = _FORBID_EXTRA

    enabled: bool = False
    base_url: str = "https://app.fleetq.net"
    api_token_env: str = "FLEETQ_API_TOKEN"
    write_trajectories: bool = True
    write_kg: bool = False
    kg_max_triples_per_call: int = Field(default=50, gt=0)
    # v2.0.0a5: which extractor produces the triples written back to
    # FleetQ KG. "heuristic" is free (regex; default); "llm" calls the
    # configured backend once per answer; "both" merges + dedups.
    kg_extractor: Literal["heuristic", "llm", "both"] = "heuristic"
    # Cap on per-call LLM triple count. The extractor honours this in
    # the prompt instruction AND post-parse truncation, so the operator
    # has a hard ceiling regardless of model behaviour.
    kg_llm_max_triples: int = Field(default=20, gt=0)
    publish_a2a_cards: bool = False
    register_as_bridge: bool = False
    heartbeat_interval: int = Field(default=30, gt=0)
    # v4.0.0a6: BridgeRelay's agent.request dispatcher worker count.
    # 1 = single-worker (v3.0.0a5 default; serial dispatch from queue).
    # >1 = bounded ThreadPoolExecutor inside the worker — only enable
    # when MCP tool thread-safety has been verified for your setup
    # (the in-process stress test in tests/integration/test_dispatcher_stress
    # can serve as a sanity check).
    dispatcher_max_workers: int = Field(default=1, gt=0, le=16)
    # v5.0.0a3: deny list for the pool. Tools listed here always run
    # on the single-worker path even when dispatcher_max_workers > 1
    # AND the tool is in dispatcher.SAFE_FOR_PARALLEL. Use this for
    # third-party plugin tools or to selectively serialise a tool that
    # turns out to share state without redeploying harbormaster.
    dispatcher_unsafe_tools: list[str] = Field(default_factory=list)


class HistoryConfig(BaseModel):
    model_config = _FORBID_EXTRA

    enabled: bool = False
    embedding_backend: Literal["fastembed", "fts5"] = "fastembed"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = Field(default=384, gt=0)
    db_dir: str = "~/.harbormaster"
    retain_recent_k: int = Field(default=1000, gt=0)
    retain_top_recalled_r: int = Field(default=100, gt=0)
    log_ask_project: bool = True
    log_delegate_task: bool = True
    log_fan_out_ask: bool = True
    default_top_k: int = Field(default=5, gt=0)
    default_min_similarity: float = Field(default=0.6, ge=0.0, le=1.0)
    auto_ground: bool = False
    auto_ground_top_k: int = Field(default=3, gt=0)
    auto_ground_max_chars: int = Field(default=8000, gt=0)
    auto_ground_min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    # v3.0.0a4: parallelize host="all" recall across local + every
    # configured host. Each per-host QAStore.open + recall runs in a
    # worker thread; results are merged identically to the sequential
    # path. Default off so existing deployments see no behavioural
    # change; opt-in for setups with many hosts where serial fan-out
    # latency adds up.
    parallel_recall: bool = False
    parallel_recall_max_workers: int = Field(default=4, gt=0, le=32)
    # v4.0.0a5: when True, an embedding-model drift detected at
    # QAStore.open() triggers an in-process reembed in a background
    # thread instead of just logging a warning. Defaults to False to
    # preserve the v3 "operator decides" behaviour.
    auto_reembed_on_drift: bool = False
    # v6.0.0a2: how long an optimistic trajectory entry can sit before
    # the UI flips its visual tier. Three tiers driven by this number:
    #   age 0..N           → cyan "● new" badge (fresh)
    #   age N..(N×6)       → amber spinner (stale — writeback in flight)
    #   age >(N×6)         → red "writeback stuck?" badge (escalation)
    # Default 5 (so 5s/30s thresholds). Operators on slow networks can
    # bump this without recompiling.
    optimistic_stale_seconds: int = Field(default=5, gt=0, le=600)


class RetentionConfig(BaseModel):
    """v12.0.0a3: operator-configurable retention caps for the UI's
    persistent stores. Hard-coded defaults from v11 are preserved when
    the operator doesn't set anything.

    - `network_log_max_rows`: rolling cap on `mcp_calls` rows in
      `~/.harbormaster/network_log.db`. v11 hard-coded 5000.
    - `memory_revisions_per_file`: rolling cap on revisions per
      (project, file) tuple in `memory_revisions.db`. v11 hard-coded 20.
    - `qa_log_recent_k` / `qa_log_top_recalled_r`: surface the existing
      `[history] retain_recent_k` / `retain_top_recalled_r` here too
      so all retention knobs live in one section. When set, these
      override the values in `[history]` for the QAStore.prune call.
      Default `None` (use the [history] values unchanged).
    """

    model_config = _FORBID_EXTRA

    network_log_max_rows: int = Field(default=5000, gt=0)
    memory_revisions_per_file: int = Field(default=20, gt=0)
    qa_log_recent_k: int | None = Field(default=None, gt=0)
    qa_log_top_recalled_r: int | None = Field(default=None, gt=0)


class PluginsConfig(BaseModel):
    """v2.0.0a4 — entry-point plugin discovery config."""

    model_config = _FORBID_EXTRA

    enabled: bool = False
    # Allowlist of distribution package names; empty allowlist means
    # NO plugins are loaded even when enabled = true (deny-by-default).
    allow: list[str] = Field(default_factory=list)



class BudgetConfig(BaseModel):
    """v15.0.0a4 — per-tool soft call budgets.

    Counterpart to ``HostConfig.daily_call_budget`` which tracks
    per-host call volume. ``daily_call_budget_per_tool`` is a
    ``{tool_name: int}`` map; tools NOT listed have no budget
    tracked. Budgets are surfaced via ``GET /api/tools/budget`` and
    on the dashboard KPI strip when v14.0.0a4's
    ``hosts-budget`` cell is hovered (it expands to show the
    per-tool breakdown).

    Empty map = no per-tool budgets configured (the v14 per-host
    budget remains the only call-volume guard). All values must be
    > 0; setting a 0 budget would mean "always over budget" which
    is never useful.
    """

    model_config = _FORBID_EXTRA

    daily_call_budget_per_tool: dict[str, int] = Field(default_factory=dict)

    @field_validator("daily_call_budget_per_tool")
    @classmethod
    def _validate_positive(cls, v: dict[str, int]) -> dict[str, int]:
        for tool, budget in v.items():
            if budget <= 0:
                raise ValueError(
                    f"daily_call_budget_per_tool[{tool!r}] must be > 0; "
                    f"got {budget}",
                )
        return v



class MarkdownConfig(BaseModel):
    """v15.0.0a6 — markdown render allowlist tuning.

    The default ``strict = True`` matches the v11.0.0a3 bleach
    allowlist exactly: standard markdown tags + tables + footnote
    markup, no extras. Setting ``strict = false`` widens the allowlist
    to also accept ``<span>``, ``<kbd>``, ``<mark>``, ``<figure>``,
    ``<figcaption>`` — useful for memory files that lean on richer
    semantic markup.

    Per-project override: drop a ``.harbormaster.toml`` at the
    project root with::

        [markdown]
        strict = false

    The render endpoint resolves the per-project value first; if no
    per-project override is present (or no project context is given),
    the global ``[markdown]`` value applies. Falls through to the
    default (``True``) when nothing is configured.

    Note: ``strict = false`` is still bleach-sanitised — protocols,
    attributes, and the broader tag/script-injection rails are
    unchanged. The flag only widens the tag allowlist.
    """

    model_config = _FORBID_EXTRA

    strict: bool = True


class IgnoreConfig(BaseModel):
    """v10.0.0a4: top-level project ignore patterns.

    Distinct from `ProjectsConfig.exclude` (which has been around since
    v1 and matches gitignore-style component names): `ignore.patterns`
    is glob-matched against the project's basename + full path via
    `fnmatch.fnmatchcase`. Both lists are applied at discovery time;
    a project is hidden if it matches EITHER list.

    Use ignore.patterns for project-name globs (`*-ui`, `*-archive`)
    that don't naturally fit the gitignore-style component model.
    """

    model_config = _FORBID_EXTRA

    patterns: list[str] = Field(default_factory=list)


class UIConfig(BaseModel):
    """v21.0.0a3 — operator-tunable accent color.

    `accent_hue` is the OKLCH hue (0-360); `accent_chroma` is the
    OKLCH chroma (0-0.30). Defaults match the v19.0.0a4 Linear-style
    violet baked into base.html (hue=290, chroma=0.22). When the
    operator overrides these via the dashboard accent picker, the
    PUT /api/settings/accent endpoint rewrites this section atomically
    in `~/.config/harbormaster/config.toml`.
    """

    model_config = _FORBID_EXTRA

    accent_hue: float = 290.0
    accent_chroma: float = 0.22


class HarbormasterConfig(BaseModel):
    model_config = _FORBID_EXTRA

    server: ServerConfig = Field(default_factory=ServerConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    backends: dict[str, BackendConfig] = Field(default_factory=lambda: {"claude": BackendConfig()})
    # v2.0.0a3: which backend should be used when no per-project
    # override is specified. Falls through to "claude" so v1
    # configs work unchanged.
    default_backend: str = "claude"
    # v2.0.0a3: optional per-project backend override map. Keys are
    # project names (matching `manifest.name`); values are backend
    # names that must exist in `backends`. Missing project names fall
    # through to `default_backend`.
    backends_for_project: dict[str, str] = Field(default_factory=dict)
    hosts: dict[str, HostConfig] = Field(default_factory=dict)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    fleetq: FleetQConfig = Field(default_factory=FleetQConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    # v12.0.0a3: surfaces the previously hard-coded retention caps so
    # large deployments can crank them up without recompiling.
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    # v15.0.0a4: per-tool soft call budgets — operator-side warning
    # surface, not enforcement. Empty by default.
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    # v15.0.0a6: markdown render allowlist tuning. Per-project overrides
    # via <project>/.harbormaster.toml. Defaults to strict.
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser()


def _config_search_paths() -> list[Path]:
    xdg = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return [
        Path.cwd() / ".harbormaster.toml",
        _expand(xdg) / "harbormaster" / "config.toml",
    ]


def load_config(path: Path | None = None) -> HarbormasterConfig:
    """Load config from TOML. Returns defaults if no file is found.

    Raises pydantic ValidationError on schema mismatch.
    """
    candidates = [path] if path is not None else _config_search_paths()

    for p in candidates:
        if p.is_file():
            with p.open("rb") as f:
                data = tomllib.load(f)
            return HarbormasterConfig.model_validate(data)
    return HarbormasterConfig()
