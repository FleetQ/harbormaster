"""Backend implementations for spawning per-project subagents."""

from collections.abc import Callable

from harbormaster.backends.base import Backend, BackendError, BackendResult
from harbormaster.backends.claude import ClaudeBackend
from harbormaster.backends.codex import CodexBackend
from harbormaster.config import BackendConfig, HarbormasterConfig

# Map backend name → factory. Adding a new backend = drop an entry
# here and ship a config block. Plugin-loaded backends (v2.0.0a4) will
# also register here at runtime.
_BACKEND_CLASSES: dict[str, Callable[[BackendConfig], Backend]] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
}


def get_backend(config: HarbormasterConfig, name: str = "claude") -> Backend | None:
    """Resolve a configured backend by name. Returns None if disabled,
    absent from config, or unknown.

    Public API since v1.0.0a4 — promoted from private `_get_backend` in
    tools/_helpers.py because cross-module imports (fan_out → _helpers)
    had made it de-facto public anyway. v2.0.0a3 widens the return type
    to the `Backend` Protocol so non-Claude backends round-trip cleanly.
    """
    cfg = config.backends.get(name)
    if cfg is None or not cfg.enabled:
        return None
    cls = _BACKEND_CLASSES.get(name)
    if cls is None:
        return None
    return cls(cfg)


def get_backend_for_project(config: HarbormasterConfig, project_name: str) -> Backend | None:
    """Return the backend configured for `project_name`, falling back
    to `config.default_backend`. Honours `[backends_for_project]`
    overrides so a single deployment can route different projects to
    Claude or Codex (or future backends) per-project.
    """
    name = config.backends_for_project.get(project_name, config.default_backend)
    return get_backend(config, name)


__all__ = [
    "Backend",
    "BackendError",
    "BackendResult",
    "ClaudeBackend",
    "CodexBackend",
    "get_backend",
    "get_backend_for_project",
]
