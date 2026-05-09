"""Cross-project graph assembly.

Given a list of `ProjectManifest`s, build a `ProjectGraph` whose
edges connect a project to its dependency only when that dependency
matches another project's manifest name. This filters out the long
tail of pure-library deps (npm, pip, composer registries) that would
otherwise drown the graph in nodes the user doesn't care about.

The `graph_to_mermaid()` helper renders a Mermaid `graph LR ...`
string for the Live UI widget.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from harbormaster.graph.parser import ProjectManifest

# Per-language adapters mapping a project's canonical name to all
# strings other projects might list it under in their manifest deps.
# composer uses `vendor/pkg`; npm uses `name`; etc. — we collect all
# plausible aliases up front so the graph builder can match via set
# membership in O(1).


def _aliases(manifest: ProjectManifest) -> set[str]:
    name = manifest.name
    aliases = {name, name.lower()}
    if "/" in name:
        # composer-style — also alias the bare package portion.
        aliases.add(name.split("/", 1)[1].lower())
    return aliases


@dataclass(frozen=True)
class GraphEdge:
    src: str          # project name (manifest.name) — edge originates here
    dst: str          # project name on the other end
    dep_kind: Literal["dep", "dev_dep"]  # source list it came from

    def as_dict(self) -> dict[str, object]:
        return {"src": self.src, "dst": self.dst, "kind": self.dep_kind}


@dataclass(frozen=True)
class GraphNode:
    name: str         # canonical (manifest.name)
    language: str
    path: str
    version: str | None = None
    description: str | None = None

    def as_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "name": self.name,
            "language": self.language,
            "path": self.path,
        }
        if self.version is not None:
            d["version"] = self.version
        if self.description is not None:
            d["description"] = self.description
        return d


@dataclass(frozen=True)
class ProjectGraph:
    nodes: tuple[GraphNode, ...] = field(default_factory=tuple)
    edges: tuple[GraphEdge, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "nodes": [n.as_dict() for n in self.nodes],
            "edges": [e.as_dict() for e in self.edges],
        }


def build_graph(
    manifests: list[ProjectManifest], *, include_dev_deps: bool = False
) -> ProjectGraph:
    """Assemble nodes + edges from a list of manifests.

    Edge filter: include only when the dep name matches some other
    project's alias set. This is what makes the graph readable —
    we don't draw a node for every npm package on disk.
    """
    nodes = tuple(
        GraphNode(
            name=m.name,
            language=m.language,
            path=m.path,
            version=m.version,
            description=m.description,
        )
        for m in manifests
    )

    alias_to_canonical: dict[str, str] = {}
    for m in manifests:
        for alias in _aliases(m):
            alias_to_canonical.setdefault(alias, m.name)

    edges_set: set[GraphEdge] = set()
    for m in manifests:
        for dep in m.deps:
            target = alias_to_canonical.get(dep) or alias_to_canonical.get(dep.lower())
            if target and target != m.name:
                edges_set.add(GraphEdge(src=m.name, dst=target, dep_kind="dep"))
        if include_dev_deps:
            for dep in m.dev_deps:
                target = alias_to_canonical.get(dep) or alias_to_canonical.get(dep.lower())
                if target and target != m.name:
                    edges_set.add(GraphEdge(src=m.name, dst=target, dep_kind="dev_dep"))

    edges = tuple(sorted(edges_set, key=lambda e: (e.src, e.dst)))
    return ProjectGraph(nodes=nodes, edges=edges)


# --- mermaid render -----------------------------------------------------

_MERMAID_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def _mermaid_id(name: str) -> str:
    """Mermaid node ids must be alphanumerics; we map composer's
    `vendor/pkg` and npm's `@scope/pkg` to safe ids while preserving
    the original name in the node label."""
    return _MERMAID_ID_SAFE_RE.sub("_", name) or "node"


def graph_to_mermaid(graph: ProjectGraph) -> str:
    """Render `graph LR` Mermaid markup. Emits one node line per
    GraphNode (so isolated nodes still appear) plus one edge line per
    GraphEdge."""
    lines = ["graph LR"]
    for node in graph.nodes:
        node_id = _mermaid_id(node.name)
        # Quote labels containing characters Mermaid would interpret.
        label = node.name.replace('"', '\\"')
        lines.append(f'  {node_id}["{label}"]')
    for edge in graph.edges:
        src_id = _mermaid_id(edge.src)
        dst_id = _mermaid_id(edge.dst)
        arrow = "-->" if edge.dep_kind == "dep" else "-.->"
        lines.append(f"  {src_id} {arrow} {dst_id}")
    return "\n".join(lines)
