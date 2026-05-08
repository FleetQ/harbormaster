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

from pydantic import BaseModel, Field


class ProjectsConfig(BaseModel):
    glob: list[str] = Field(default_factory=lambda: ["~/htdocs/*"])
    exclude: list[str] = Field(default_factory=list)
    require_marker: bool = False


class BackendConfig(BaseModel):
    enabled: bool = True
    binary: str = "claude"
    extra_args: list[str] = Field(default_factory=lambda: ["-p"])
    timeout_local: int = 60
    timeout_remote: int = 120
    output_word_cap: int = 800


class HostConfig(BaseModel):
    ssh_host: str
    remote_htdocs: str = "~/htdocs"
    backend: str = "claude"
    connect_timeout: int = 10
    total_timeout: int = 120


class ServerConfig(BaseModel):
    ui_port: int = 7531
    mcp_http_port: int = 7532
    log_level: str = "info"
    trajectory_retention_days: int = 90


class StorageConfig(BaseModel):
    db_path: str = "~/.local/share/harbormaster/harbormaster.db"
    enable_dedup: bool = False


class FleetQConfig(BaseModel):
    enabled: bool = False
    base_url: str = "https://app.fleetq.net"
    api_token_env: str = "FLEETQ_API_TOKEN"
    write_trajectories: bool = True
    publish_a2a_cards: bool = False
    register_as_bridge: bool = False
    heartbeat_interval: int = 30


class HarbormasterConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    backends: dict[str, BackendConfig] = Field(
        default_factory=lambda: {"claude": BackendConfig()}
    )
    hosts: dict[str, HostConfig] = Field(default_factory=dict)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    fleetq: FleetQConfig = Field(default_factory=FleetQConfig)


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
