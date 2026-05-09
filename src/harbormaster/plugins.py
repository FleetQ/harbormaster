"""Entry-point-based plugin discovery (v2.0.0a4).

Third-party packages can ship MCP tools that load alongside the
built-in ones. To register, a plugin distribution declares an entry
point in the `harbormaster.tools` group:

    [project.entry-points."harbormaster.tools"]
    my-plugin = "my_plugin.module:register"

The target callable must match the contract:

    def register(mcp: FastMCP, config: HarbormasterConfig) -> None: ...

This is identical to the contract used by built-in tools — plugins are
just additional `register_*` functions that get called after the
built-ins, by the same `register_tools` orchestrator.

Three gates protect operators from accidentally loading code:

  1. `[plugins] enabled = true`            (default false — opt in)
  2. `[plugins] allow = ["dist-name", ...]` (allowlist; default empty
     means every entry point is REJECTED — explicit allowlist required
     to avoid drive-by loading)
  3. The plugin's `register()` must not raise — failures are caught,
     logged at WARNING, and the plugin is skipped without affecting
     the rest of startup.

The allowlist is matched against the entry point's *distribution
package name*, NOT the entry point name itself — because the
distribution name is what the operator installed (`pip install
harbormaster-plugin-foo`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from harbormaster.config import HarbormasterConfig

logger = logging.getLogger("harbormaster.plugins")

ENTRY_POINT_GROUP = "harbormaster.tools"

PluginRegister = Callable[["FastMCP", "HarbormasterConfig"], None]


def discover_entry_points() -> list[EntryPoint]:
    """Return every entry point declared under the `harbormaster.tools`
    group across all installed distributions. Pure discovery — no
    allowlist check, no load. Useful for `harbormaster-mcp plugins
    list` (deferred to v2.0.0a5+) and for tests."""
    return list(entry_points(group=ENTRY_POINT_GROUP))


def _entry_point_distribution_name(ep: EntryPoint) -> str | None:
    """Return the distribution package name that owns an entry point,
    or None when the lookup fails (very old metadata schemas).

    `EntryPoint.dist` exists since Python 3.10; older packaging tools
    sometimes ship distributions without it filled in, so we fall back
    to None and let the allowlist check reject the plugin."""
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None) or getattr(dist, "metadata", None)
    if isinstance(name, str):
        return name
    if name is not None and hasattr(name, "__getitem__"):
        # importlib.metadata.PackageMetadata behaves like a Mapping
        return str(name["Name"])
    return None


def load_plugins(
    mcp: FastMCP,
    config: HarbormasterConfig,
) -> list[str]:
    """Load every entry point matching the allowlist under
    `[plugins].allow`. Returns the list of successfully loaded
    distribution names — useful for startup logging and for
    introspection at the operator side. Failures are caught + logged;
    they never propagate to the caller.

    Returns an empty list (and a single debug-level log line) when
    `[plugins].enabled` is false, so operators see nothing in the logs
    when they haven't opted in.
    """
    if not config.plugins.enabled:
        logger.debug("plugins disabled; skipping discovery")
        return []

    allowlist = set(config.plugins.allow)
    if not allowlist:
        logger.warning(
            "plugins enabled but [plugins].allow is empty — every entry "
            "point will be rejected. Add `allow = ['package-name']` to "
            "load specific plugins."
        )
        return []

    loaded: list[str] = []
    for ep in discover_entry_points():
        dist_name = _entry_point_distribution_name(ep)
        if dist_name is None or dist_name not in allowlist:
            logger.info(
                "plugin %r (entry point %r) not in [plugins].allow; skipping",
                dist_name,
                ep.name,
            )
            continue
        try:
            register_fn = ep.load()
        except Exception:  # noqa: BLE001 - plugin import is unsafe by definition
            logger.warning(
                "plugin %r failed to import; skipping. See log for traceback.",
                dist_name,
                exc_info=True,
            )
            continue
        if not callable(register_fn):
            logger.warning(
                "plugin %r entry point %r is not callable; skipping",
                dist_name,
                ep.name,
            )
            continue
        try:
            register_fn(mcp, config)
        except Exception:  # noqa: BLE001 - plugin code is untrusted
            logger.warning(
                "plugin %r register() raised; tool not registered. See log for traceback.",
                dist_name,
                exc_info=True,
            )
            continue
        loaded.append(dist_name)
        logger.info("loaded plugin %r (entry point %r)", dist_name, ep.name)
    return loaded
