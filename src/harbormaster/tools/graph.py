"""project_graph MCP tool — auto-discovered project dependency graph (v1.2 phase 3)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.graph import (
    ManifestCache,
    build_graph,
    graph_to_mermaid,
)
from harbormaster.projects import discover_projects

logger = logging.getLogger("harbormaster.tools.graph")

# One ManifestCache instance per server — populated lazily on first call,
# refreshed on manifest mtime change. Module-level so independent tool
# calls share results.
_cache = ManifestCache()


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def project_graph(
        format: Literal["json", "mermaid"] = "json",
        include_dev_deps: bool = False,
    ) -> dict[str, object]:
        """Return the cross-project dependency graph for all locally
        discovered projects.

        Parses each project's manifest (composer.json, package.json,
        pyproject.toml, Cargo.toml, go.mod) and produces a graph whose
        edges connect a project to its dependency only when that
        dependency matches another known project's manifest name. The
        long tail of pure-library deps is filtered out so the graph
        stays readable.

        Args:
          format: "json" (default — returns nodes + edges + manifests)
            or "mermaid" (also includes a `mermaid` field with a
            `graph LR` markup string for direct rendering).
          include_dev_deps: include dev/test/peer deps as edges
            (rendered with dotted arrows in Mermaid). Default false.
        """
        manifests = []
        for p in discover_projects(config.projects):
            m = _cache.get(Path(p.path))
            if m is not None:
                manifests.append(m)

        graph = build_graph(manifests, include_dev_deps=include_dev_deps)
        result: dict[str, object] = {
            "projects_discovered": len(manifests),
            "manifests": [m.as_dict() for m in manifests],
            "graph": graph.as_dict(),
        }
        if format == "mermaid":
            result["mermaid"] = graph_to_mermaid(graph)
        return result
