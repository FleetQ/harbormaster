"""Local project discovery and resolution from configured globs."""
from __future__ import annotations

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
    """Extract the literal base directory of a glob pattern (the prefix before
    the first wildcard). Returns None for patterns that don't have a meaningful
    base (e.g. `*` alone)."""
    expanded = str(Path(pattern).expanduser())
    star_idx = -1
    for ch in ("*", "?"):
        i = expanded.find(ch)
        if i >= 0 and (star_idx < 0 or i < star_idx):
            star_idx = i
    if star_idx < 0:
        return Path(expanded).resolve() if Path(expanded).exists() else None
    base_str = expanded[:star_idx].rstrip("/")
    if not base_str:
        return None
    base = Path(base_str)
    return base.resolve() if base.is_dir() else None


def _is_under_any_base(path: Path, bases: list[Path]) -> bool:
    """Containment check: True if `path` is under any of `bases` (after resolving)."""
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


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    s = str(path)
    for pat in patterns:
        # Strip leading ** for naive substring match — adequate for v1.0
        normalized = pat.replace("**/", "").replace("/**", "")
        if normalized and normalized in s:
            return True
    return False


def discover_projects(config: ProjectsConfig) -> list[ProjectInfo]:
    """Walk configured globs and return ProjectInfo for every directory that
    looks like a project. Sorted by last commit date desc.

    Containment guard: a child whose resolved path leaves the resolved base
    directory of every configured glob (e.g. via a symlink to /etc/foo) is
    skipped. This prevents discovery from following symlinks out of the
    user's intended project space.
    """
    bases = [b for p in config.glob if (b := _glob_base(p)) is not None]
    seen: set[Path] = set()
    projects: list[ProjectInfo] = []

    for pattern in config.glob:
        expanded_str = str(Path(pattern).expanduser())
        if "*" in expanded_str or "?" in expanded_str:
            star_idx = min(
                (i for i in (expanded_str.find("*"), expanded_str.find("?")) if i >= 0),
                default=-1,
            )
            base_str = expanded_str[:star_idx].rstrip("/")
            glob_fragment = expanded_str[len(base_str):].lstrip("/") or "*"
            base = Path(base_str)
            if not base.is_dir():
                continue
            children = list(base.glob(glob_fragment))
        else:
            p = Path(expanded_str)
            children = [p] if p.exists() else []

        for child in children:
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
                # Symlink (or relative climb) out of the configured base. Skip.
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
    """Return the local path for a project by name. Raises ValueError on
    invalid name OR when the project is not found among discovered projects.

    Always validates `name` against the strict regex first so callers can rely
    on it rejecting traversal attempts before any filesystem walk happens.
    """
    validate_project_name(name)
    candidates = discover_projects(config)
    for c in candidates:
        if c.name == name:
            return Path(c.path)
    available = ", ".join(p.name for p in candidates[:20])
    raise ValueError(f"project '{name}' not found. Available: {available}")
