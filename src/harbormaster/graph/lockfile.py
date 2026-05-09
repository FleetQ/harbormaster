"""Per-language lockfile parsers (v2.0.0a1).

Each parser returns the set of package names recorded in the lockfile —
not the manifest's direct deps, but the *transitive* set that the
package manager would actually install. We deliberately ignore version
specifiers, source URLs, and inner edges between transitive packages:
the graph's edges are only drawn when a transitive dep matches another
known project's manifest name, so just the name set is enough.

A missing or unparseable lockfile returns None — the graph builder then
falls back to manifest-only direct deps (v1 behaviour).

Supported lockfiles:
    Python:     uv.lock, poetry.lock, requirements.txt
    JavaScript: package-lock.json
    PHP:        composer.lock
    Rust:       Cargo.lock
    Go:         go.sum

`pnpm-lock.yaml` and `yarn.lock` are deliberately deferred — both are
YAML / custom formats that need a heavier parser; the v2.0.0a1 cut
covers the formats most projects on this user's machine actually use.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("harbormaster.graph.lockfile")

LockfileParser = Callable[[Path], "set[str] | None"]


# Language → list of (filename, parser) pairs in priority order. The
# graph cache picks the first lockfile that exists; later parsers are
# only consulted when earlier ones miss. Ordering reflects observed
# adoption in this user's htdocs (uv > poetry > requirements; npm
# package-lock first since it's most common).
def parse_uv_lock(path: Path) -> set[str] | None:
    """Parse a uv.lock (TOML — uv >= 0.4) returning every package name."""
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("uv.lock parse failed for %s: %s", path, e)
        return None

    packages = data.get("package") or []
    if not isinstance(packages, list):
        return None
    out: set[str] = set()
    for pkg in packages:
        if isinstance(pkg, dict):
            name = pkg.get("name")
            if isinstance(name, str) and name:
                out.add(name)
    return out


def parse_poetry_lock(path: Path) -> set[str] | None:
    """Parse a poetry.lock (TOML) — `[[package]]` array of tables."""
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("poetry.lock parse failed for %s: %s", path, e)
        return None

    packages = data.get("package") or []
    if not isinstance(packages, list):
        return None
    out: set[str] = set()
    for pkg in packages:
        if isinstance(pkg, dict):
            name = pkg.get("name")
            if isinstance(name, str) and name:
                out.add(name)
    return out


# pip-style requirement files: one requirement per non-comment line.
# Strip everything from the first PEP 508 separator onward, mirroring
# parser._strip_pep508_specifiers but for the lockfile context.
_REQUIREMENTS_LINE_RE = re.compile(r"[<>=!~\s\[;#]")


def parse_requirements_txt(path: Path) -> set[str] | None:
    """Parse a requirements.txt file — one pinned package per line."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.debug("requirements.txt read failed for %s: %s", path, e)
        return None
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            # Skip blanks, comments, and pip option lines like `-r other.txt`.
            continue
        # Drop URL form `pkg @ git+...` cleanly: split on the marker too.
        head = _REQUIREMENTS_LINE_RE.split(line, 1)[0].strip()
        if head:
            out.add(head)
    return out


def parse_package_lock_json(path: Path) -> set[str] | None:
    """Parse a JS package-lock.json (npm v1, v2, or v3)."""
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("package-lock.json parse failed for %s: %s", path, e)
        return None

    out: set[str] = set()
    # npm v2/v3: `packages` keyed by install path; `""` is the root.
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, pkg in packages.items():
            if not isinstance(pkg, dict) or not key:
                # Skip the root entry — its name belongs to the manifest,
                # not the transitive set.
                continue
            # Derive name from path first, since the inner `name` field
            # can be missing on transitive entries:
            #   "node_modules/@scope/name" → "@scope/name"
            #   "node_modules/foo/node_modules/bar" → "bar"
            segments = key.split("node_modules/")
            derived = segments[-1] if len(segments) > 1 else None
            name = derived or pkg.get("name")
            if isinstance(name, str) and name:
                out.add(name)
    # npm v1: `dependencies` recursive map.
    if not out:
        dependencies = data.get("dependencies")
        if isinstance(dependencies, dict):
            _walk_npm_v1_dependencies(dependencies, out)
    return out


def _walk_npm_v1_dependencies(node: dict[str, object], out: set[str]) -> None:
    for name, sub in node.items():
        if isinstance(name, str) and name:
            out.add(name)
        if isinstance(sub, dict):
            inner = sub.get("dependencies")
            if isinstance(inner, dict):
                _walk_npm_v1_dependencies(inner, out)


def parse_composer_lock(path: Path) -> set[str] | None:
    """Parse composer.lock — `packages` and `packages-dev` arrays."""
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("composer.lock parse failed for %s: %s", path, e)
        return None

    out: set[str] = set()
    for key in ("packages", "packages-dev"):
        arr = data.get(key) or []
        if not isinstance(arr, list):
            continue
        for pkg in arr:
            if isinstance(pkg, dict):
                name = pkg.get("name")
                if isinstance(name, str) and name:
                    out.add(name)
    return out


def parse_cargo_lock(path: Path) -> set[str] | None:
    """Parse Cargo.lock — TOML with `[[package]]` array."""
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("Cargo.lock parse failed for %s: %s", path, e)
        return None
    packages = data.get("package") or []
    if not isinstance(packages, list):
        return None
    out: set[str] = set()
    for pkg in packages:
        if isinstance(pkg, dict):
            name = pkg.get("name")
            if isinstance(name, str) and name:
                out.add(name)
    return out


_GO_SUM_LINE_RE = re.compile(r"^(\S+)\s+v\S+\s+h1:")


def parse_go_sum(path: Path) -> set[str] | None:
    """Parse go.sum — every line `<module> <version> h1:<hash>`. We only
    keep the module name (one per dep, ignoring `<version>/go.mod` lines)."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.debug("go.sum read failed for %s: %s", path, e)
        return None
    out: set[str] = set()
    for line in text.splitlines():
        m = _GO_SUM_LINE_RE.match(line)
        if m:
            out.add(m.group(1))
    return out


# Map language → ordered candidate lockfile filenames + parser. The
# first matching file in the project root wins.
LOCKFILE_CANDIDATES: dict[str, tuple[tuple[str, LockfileParser], ...]] = {
    "python": (
        ("uv.lock", parse_uv_lock),
        ("poetry.lock", parse_poetry_lock),
        ("requirements.txt", parse_requirements_txt),
    ),
    "javascript": (("package-lock.json", parse_package_lock_json),),
    "php": (("composer.lock", parse_composer_lock),),
    "rust": (("Cargo.lock", parse_cargo_lock),),
    "go": (("go.sum", parse_go_sum),),
}


def find_lockfile(project_path: Path, language: str) -> Path | None:
    """Return the first lockfile that exists for `language` in
    `project_path`, or None when no candidate matches."""
    for filename, _parser in LOCKFILE_CANDIDATES.get(language, ()):
        candidate = project_path / filename
        if candidate.is_file():
            return candidate
    return None


def parse_lockfile(project_path: Path, language: str) -> tuple[Path, set[str]] | None:
    """Discover and parse the project's lockfile for `language`. Returns
    `(lockfile_path, package_names)` on success, or None when no lockfile
    is present or parsing failed."""
    for filename, parser in LOCKFILE_CANDIDATES.get(language, ()):
        candidate = project_path / filename
        if candidate.is_file():
            packages = parser(candidate)
            if packages is not None:
                return candidate, packages
    return None
