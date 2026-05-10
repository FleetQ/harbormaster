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
        transitive: bool = False,
    ) -> dict[str, object]:
        """Return the cross-project dependency graph for all locally
        discovered projects.

        Parses each project's manifest (composer.json, package.json,
        pyproject.toml, Cargo.toml, go.mod) and produces a graph whose
        edges connect a project to its dependency only when that
        dependency matches another known project's manifest name. The
        long tail of pure-library deps is filtered out so the graph
        stays readable.

        When `transitive=True` (v2.0.0a1), the project's lockfile is
        also consulted (uv.lock, poetry.lock, requirements.txt,
        package-lock.json, composer.lock, Cargo.lock, go.sum) and any
        transitive dep that matches another known project becomes an
        additional edge with `kind="transitive"`. Falls back to manifest
        deps when no lockfile is present.

        Args:
          format: "json" (default — returns nodes + edges + manifests)
            or "mermaid" (also includes a `mermaid` field with a
            `graph LR` markup string for direct rendering).
          include_dev_deps: include dev/test/peer deps as edges
            (rendered with dotted arrows in Mermaid). Default false.
          transitive: include lockfile-resolved transitive deps as
            edges. Default false.
        """
        manifests = []
        for p in discover_projects(config.projects, ignore_patterns=config.ignore.patterns):
            m = _cache.get(Path(p.path))
            if m is not None:
                manifests.append(m)

        graph = build_graph(
            manifests,
            include_dev_deps=include_dev_deps,
            transitive=transitive,
        )
        result: dict[str, object] = {
            "projects_discovered": len(manifests),
            "projects_with_lockfile": sum(
                1 for m in manifests if m.lockfile is not None
            ),
            "manifests": [m.as_dict() for m in manifests],
            "graph": graph.as_dict(),
        }
        if format == "mermaid":
            result["mermaid"] = graph_to_mermaid(graph)
        return result
