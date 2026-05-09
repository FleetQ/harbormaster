"""Auto project graph (v1.2 phase 3).

Parses per-project manifest files (composer.json, package.json,
pyproject.toml, Cargo.toml, go.mod) and builds a cross-project
dependency graph: edges are drawn only when one project's dep matches
another known project's manifest name. The result powers a Live UI
Mermaid widget and the `project_graph` MCP tool.

Pure file parsing — no LLM, no network, no FleetQ dependency.
"""
from __future__ import annotations

from harbormaster.graph.builder import ProjectGraph, build_graph, graph_to_mermaid
from harbormaster.graph.cache import ManifestCache
from harbormaster.graph.lockfile import (
    LOCKFILE_CANDIDATES,
    find_lockfile,
    parse_cargo_lock,
    parse_composer_lock,
    parse_go_sum,
    parse_lockfile,
    parse_package_lock_json,
    parse_poetry_lock,
    parse_requirements_txt,
    parse_uv_lock,
)
from harbormaster.graph.parser import (
    ProjectManifest,
    parse_cargo_toml,
    parse_composer_json,
    parse_go_mod,
    parse_package_json,
    parse_project,
    parse_pyproject_toml,
)

__all__ = [
    "LOCKFILE_CANDIDATES",
    "ManifestCache",
    "ProjectGraph",
    "ProjectManifest",
    "build_graph",
    "find_lockfile",
    "graph_to_mermaid",
    "parse_cargo_lock",
    "parse_cargo_toml",
    "parse_composer_json",
    "parse_composer_lock",
    "parse_go_mod",
    "parse_go_sum",
    "parse_lockfile",
    "parse_package_json",
    "parse_package_lock_json",
    "parse_poetry_lock",
    "parse_project",
    "parse_pyproject_toml",
    "parse_requirements_txt",
    "parse_uv_lock",
]
