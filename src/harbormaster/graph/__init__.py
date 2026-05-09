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
    "ManifestCache",
    "ProjectGraph",
    "ProjectManifest",
    "build_graph",
    "graph_to_mermaid",
    "parse_cargo_toml",
    "parse_composer_json",
    "parse_go_mod",
    "parse_package_json",
    "parse_project",
    "parse_pyproject_toml",
]
