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

from pydantic import BaseModel, ConfigDict, Field

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


class HostConfig(BaseModel):
    model_config = _FORBID_EXTRA

    ssh_host: str
    remote_htdocs: str = "~/htdocs"
    backend: str = "claude"
    connect_timeout: int = Field(default=10, gt=0)
    total_timeout: int = Field(default=120, gt=0)


class ServerConfig(BaseModel):
    model_config = _FORBID_EXTRA

    ui_port: int = Field(default=7531, gt=0, lt=65536)
    mcp_http_port: int = Field(default=7532, gt=0, lt=65536)
    log_level: LogLevel = "info"
    trajectory_retention_days: int = Field(default=90, gt=0)


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


class PluginsConfig(BaseModel):
    """v2.0.0a4 — entry-point plugin discovery config."""

    model_config = _FORBID_EXTRA

    enabled: bool = False
    # Allowlist of distribution package names; empty allowlist means
    # NO plugins are loaded even when enabled = true (deny-by-default).
    allow: list[str] = Field(default_factory=list)


class HarbormasterConfig(BaseModel):
    model_config = _FORBID_EXTRA

    server: ServerConfig = Field(default_factory=ServerConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
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
