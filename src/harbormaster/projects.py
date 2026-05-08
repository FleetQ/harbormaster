"""Local project discovery, name validation, and resolution.

The split between this module's public functions reflects two access patterns:

- Cold/full enumeration → `discover_projects(config)` returns rich
  `ProjectInfo` (with git log, Serena flags, brief). Used by the
  `list_projects` MCP tool — pays N git subprocesses per call.

- Hot/single lookup → `find_project_path(name, config)` returns just a
  `Path` after a name match. Used by the `ask_project` / `delegate_task`
  hot paths. No git, no per-project work beyond filesystem stat.

Both share the same containment guarantees: a child whose resolved path
leaves every configured glob's base directory is rejected (closes the
symlink-out-of-base traversal vector).
"""
from __future__ import annotations

import fnmatch
import glob as _glob
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from harbormaster.config import ProjectsConfig

# Strict project-name regex: alphanumeric leading char, then alphanumeric or
# `.`/`_`/`-`. Blocks shell metas, slashes, leading dot (no `..`, no `.git`).
# This is the single trust gate before any value is interpolated into a path
# that hits the filesystem (local) or a remote shell (SSH).
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_project_name(name: str) -> None:
    """Reject names that could escape the configured project base.

    Allowed: alphanumeric, dot, underscore, hyphen, with an alphanumeric leading
    character. Rejects: '.', '..', anything with `/`, leading dot, shell metas.

    Raises ValueError with a clear message on rejection. This is the trust
    boundary for both local resolve_project and any remote path construction.
    """
    if not isinstance(name, str) or not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            f"invalid project name {name!r}: must match [A-Za-z0-9][A-Za-z0-9._-]* "
            f"(no slashes, no leading dot, no shell metas)"
        )


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    path: str
    last_commit: dict[str, str] | None
    has_serena: bool
    has_claude_md: bool
    brief: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_project(p: Path) -> bool:
    return p.is_dir() and ((p / ".git").is_dir() or (p / "CLAUDE.md").is_file())


def _glob_base(pattern: str) -> Path | None:
    """Longest non-magic path prefix of the pattern, used as the containment
    base. Returns None if no fixed prefix exists (e.g. a bare `*`)."""
    expanded = Path(pattern).expanduser()
    if not _glob.has_magic(str(expanded)):
        return expanded.resolve() if expanded.is_dir() else None
    base_parts: list[str] = []
    for part in expanded.parts:
        if _glob.has_magic(part):
            break
        base_parts.append(part)
    if not base_parts:
        return None
    base = Path(*base_parts)
    return base.resolve() if base.is_dir() else None


def _is_under_any_base(path: Path, bases: list[Path]) -> bool:
    """Containment check: True if `path` is under any of `bases` after resolving."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for base in bases:
        try:
            resolved.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    """Check if `path` matches any exclude pattern.

    Supports gitignore-style patterns:
      - `**/node_modules/**` → match if any path component is `node_modules`
      - `node_modules`       → same (treated as bare component name)
      - `*.swp`              → fnmatch against any path component
      - `/full/path/*.tmp`   → fnmatch against the full absolute path
    """
    parts = path.parts
    parts_set = set(parts)
    s = str(path)
    for raw in patterns:
        core = raw.removeprefix("**/").removesuffix("/**").strip("/")
        if not core:
            continue
        if not _glob.has_magic(core):
            # Plain name → match against any component (fast path).
            if core in parts_set:
                return True
            continue
        # Has globbing meta — fnmatch each component, then full path.
        for part in parts:
            if fnmatch.fnmatchcase(part, core):
                return True
        if fnmatch.fnmatchcase(s, raw):
            return True
    return False


def _git_last_commit(path: Path) -> dict[str, str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%h%x09%s%x09%cI"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        h, subject, date = out.stdout.strip().split("\t", 2)
        return {"hash": h, "subject": subject, "date": date}
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def _project_brief(path: Path) -> str:
    for fname in ("CLAUDE.md", "README.md", "README.txt"):
        f = path / fname
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)
                body = re.sub(r"^#.*?$", "", body, flags=re.MULTILINE).strip()
                return body[:200].replace("\n", " ").strip()
            except OSError:
                pass
    return ""


def _iter_glob_matches(config: ProjectsConfig) -> list[tuple[Path, list[Path]]]:
    """Yield (resolved_base, matches) per configured glob pattern.

    Uses stdlib `glob.iglob(recursive=True)` so `**` patterns work as expected.
    Bases are returned alongside matches so callers can do a containment check.
    """
    out: list[tuple[Path, list[Path]]] = []
    for pattern in config.glob:
        expanded = str(Path(pattern).expanduser())
        base = _glob_base(pattern)
        matches = [Path(m) for m in _glob.iglob(expanded, recursive=True)]
        if base is not None:
            out.append((base, matches))
        else:
            out.append((Path("/"), matches))  # no base → any path is "under" /
    return out


def find_project_path(name: str, config: ProjectsConfig) -> Path:
    """Fast project-by-name lookup. No git, no rich metadata, no sort.

    Walks configured globs and returns the first match whose directory name
    equals `name` and which passes the containment + exclude filters. Validates
    `name` against the strict regex first.
    """
    validate_project_name(name)
    bases_with_matches = _iter_glob_matches(config)
    bases = [b for b, _ in bases_with_matches if str(b) != "/"]

    for _base, matches in bases_with_matches:
        for child in matches:
            if child.name != name:
                continue
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if not _is_project(resolved):
                continue
            if _is_excluded(resolved, config.exclude):
                continue
            if bases and not _is_under_any_base(resolved, bases):
                continue
            if config.require_marker and not (resolved / "CLAUDE.md").is_file() \
                    and not (resolved / ".serena").is_dir():
                continue
            return resolved

    raise ValueError(f"project {name!r} not found in configured globs")


def discover_projects(config: ProjectsConfig) -> list[ProjectInfo]:
    """Walk configured globs and return rich ProjectInfo for every match.

    Sorted by last commit date desc. Pays one `git log` subprocess per match —
    use this for the list_projects MCP tool, NOT for hot lookup paths.
    """
    bases_with_matches = _iter_glob_matches(config)
    bases = [b for b, _ in bases_with_matches if str(b) != "/"]
    seen: set[Path] = set()
    projects: list[ProjectInfo] = []

    for _base, matches in bases_with_matches:
        for child in matches:
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            if not _is_project(resolved):
                continue
            if _is_excluded(resolved, config.exclude):
                continue
            if bases and not _is_under_any_base(resolved, bases):
                continue
            if config.require_marker and not (resolved / "CLAUDE.md").is_file() \
                    and not (resolved / ".serena").is_dir():
                continue
            seen.add(resolved)
            projects.append(ProjectInfo(
                name=resolved.name,
                path=str(resolved),
                last_commit=_git_last_commit(resolved),
                has_serena=(resolved / ".serena").is_dir(),
                has_claude_md=(resolved / "CLAUDE.md").is_file(),
                brief=_project_brief(resolved),
            ))

    projects.sort(
        key=lambda p: p.last_commit["date"] if p.last_commit else "",
        reverse=True,
    )
    return projects


def resolve_project(name: str, config: ProjectsConfig) -> Path:
    """Public API: return the path of a project by name.

    Now an alias for find_project_path — kept under the original name to
    preserve external API stability. Callers that need rich metadata should
    use discover_projects() and filter on .name.
    """
    return find_project_path(name, config)
