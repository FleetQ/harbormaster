"""Operator-managed per-project hide list (v21.0.5).

Server-side companion to the dashboard sidebar's "Hide" button. Operators
flag projects they don't want in their workspace surface; the UI POSTs the
name here, the state lands in JSON on disk, and `/api/projects` filters it
out on subsequent calls.

This is intentionally separate from `[ignore].patterns` in `harbormaster.toml`:

- `[ignore].patterns` is the **operator's static, version-controllable
  config** — globs that hide projects matching a rule (e.g. `tmp-*`,
  `*-archive`).
- `user_hidden` is the **dynamic, click-driven** equivalent — one
  project name at a time, persisted to `~/.harbormaster/user_hidden.json`
  and editable through the UI (Hide / Unhide buttons in the sidebar).

The two are composed at filter time: the union of "matched by an ignore
pattern" and "is in user_hidden" is hidden from `/api/projects`.

Honours `HARBORMASTER_USER_HIDDEN_FILE` env var so tests can redirect
state. Atomic temp-and-rename writes prevent torn files on crash.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from harbormaster.projects import _PROJECT_NAME_RE

logger = logging.getLogger(__name__)


def default_state_path() -> Path:
    """Resolve the on-disk state file path.

    Matches the env-override convention used by ProjectsCache,
    `HARBORMASTER_NETWORK_LOG_DB`, etc. — tests' conftest redirects here
    so the real `~/.harbormaster/` is never touched by the suite.
    """
    override = os.environ.get("HARBORMASTER_USER_HIDDEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".harbormaster" / "user_hidden.json"


class UserHiddenStore:
    """Thread-safe wrapper around the JSON state file.

    A single process-level lock guards reads + writes so concurrent
    requests from the dashboard never see a torn state. Writes go
    through a temp file + `os.replace` for atomicity on POSIX.
    """

    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path or default_state_path()
        self._lock = threading.Lock()

    def _read_locked(self) -> set[str]:
        """Read names from disk. Empty set on missing/malformed file."""
        if not self._path.exists():
            return set()
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("user_hidden: failed to read %s (%s)", self._path, e)
            return set()
        names = data.get("names") if isinstance(data, dict) else None
        if not isinstance(names, list):
            return set()
        # Trust nothing: re-validate every name on read so a corrupted
        # state file can't smuggle in a non-project-name string that
        # later flows into a path or shell.
        return {n for n in names if isinstance(n, str) and _PROJECT_NAME_RE.match(n)}

    def _write_locked(self, names: set[str]) -> None:
        """Atomic write of `names` to disk."""
        payload = json.dumps({"names": sorted(names)}, separators=(",", ":"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            dir=str(self._path.parent),
            prefix=".user_hidden.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as fh:
            fh.write(payload)
            tmp_path = Path(fh.name)
        os.replace(tmp_path, self._path)

    def list(self) -> list[str]:
        """Return the sorted list of hidden project names."""
        with self._lock:
            return sorted(self._read_locked())

    def add(self, name: str) -> bool:
        """Add `name`. Returns True if newly added, False if already present.

        Raises ValueError if `name` doesn't match the project name regex.
        """
        if not _PROJECT_NAME_RE.match(name):
            raise ValueError(f"invalid project name: {name!r}")
        with self._lock:
            names = self._read_locked()
            if name in names:
                return False
            names.add(name)
            self._write_locked(names)
            return True

    def remove(self, name: str) -> bool:
        """Remove `name`. Returns True if removed, False if not present."""
        with self._lock:
            names = self._read_locked()
            if name not in names:
                return False
            names.discard(name)
            self._write_locked(names)
            return True

    def contains(self, name: str) -> bool:
        """Membership check — cheap read."""
        with self._lock:
            return name in self._read_locked()


# Module-level default singleton — created lazily so test env-var overrides
# applied via monkeypatch before first use are still honoured.
_default_store: UserHiddenStore | None = None
_default_store_lock = threading.Lock()


def get_default_store() -> UserHiddenStore:
    """Return the process-wide default store (lazy-singleton)."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = UserHiddenStore()
        return _default_store


def reset_default_store_for_tests() -> None:
    """Force a re-init on next access. Called by test fixtures only."""
    global _default_store
    with _default_store_lock:
        _default_store = None
