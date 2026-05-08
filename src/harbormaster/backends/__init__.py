"""Backend implementations for spawning per-project subagents."""
from harbormaster.backends.base import Backend, BackendError, BackendResult
from harbormaster.backends.claude import ClaudeBackend
from harbormaster.config import HarbormasterConfig


def get_backend(config: HarbormasterConfig, name: str = "claude") -> ClaudeBackend | None:
    """Resolve a configured backend by name. Returns None if disabled or absent.

    Public API since v1.0.0a4 — promoted from private `_get_backend` in
    tools/_helpers.py because cross-module imports (fan_out → _helpers) had
    made it de-facto public anyway.
    """
    cfg = config.backends.get(name)
    if cfg is None or not cfg.enabled:
        return None
    return ClaudeBackend(cfg)


__all__ = [
    "Backend",
    "BackendError",
    "BackendResult",
    "ClaudeBackend",
    "get_backend",
]
