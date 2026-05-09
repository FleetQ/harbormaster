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
    publish_a2a_cards: bool = False
    register_as_bridge: bool = False
    heartbeat_interval: int = Field(default=30, gt=0)



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


class HarbormasterConfig(BaseModel):
    model_config = _FORBID_EXTRA

    server: ServerConfig = Field(default_factory=ServerConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    backends: dict[str, BackendConfig] = Field(
        default_factory=lambda: {"claude": BackendConfig()}
    )
    hosts: dict[str, HostConfig] = Field(default_factory=dict)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    fleetq: FleetQConfig = Field(default_factory=FleetQConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)


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
