"""Local project discovery and resolution from configured globs."""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from harbormaster.config import ProjectsConfig


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    path: str
    last_commit: dict[str, str] | None
    has_serena: bool
    has_claude_md: bool
    brief: str

    def as_dict(self) -> dict:
        return asdict(self)


def _is_project(p: Path) -> bool:
    return p.is_dir() and ((p / ".git").is_dir() or (p / "CLAUDE.md").is_file())


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
    looks like a project. Sorted by last commit date desc."""
    seen: set[Path] = set()
    projects: list[ProjectInfo] = []

    for pattern in config.glob:
        expanded_str = str(Path(pattern).expanduser())
        # Split a glob like ~/htdocs/* into base + glob fragment
        if "*" in expanded_str or "?" in expanded_str:
            star_idx = min(
                (i for i in (expanded_str.find("*"), expanded_str.find("?")) if i >= 0),
                default=-1,
            )
            base_str = expanded_str[: star_idx].rstrip("/")
            glob_fragment = expanded_str[len(base_str):].lstrip("/") or "*"
            base = Path(base_str)
            if not base.is_dir():
                continue
            children = list(base.glob(glob_fragment))
        else:
            p = Path(expanded_str)
            children = [p] if p.exists() else []

        for child in children:
            child = child.resolve()
            if child in seen:
                continue
            if not _is_project(child):
                continue
            if _is_excluded(child, config.exclude):
                continue
            if config.require_marker and not (child / "CLAUDE.md").is_file() \
                    and not (child / ".serena").is_dir():
                continue
            seen.add(child)
            projects.append(ProjectInfo(
                name=child.name,
                path=str(child),
                last_commit=_git_last_commit(child),
                has_serena=(child / ".serena").is_dir(),
                has_claude_md=(child / "CLAUDE.md").is_file(),
                brief=_project_brief(child),
            ))

    projects.sort(
        key=lambda p: p.last_commit["date"] if p.last_commit else "",
        reverse=True,
    )
    return projects


def resolve_project(name: str, config: ProjectsConfig) -> Path:
    """Return the local path for a project by name. Raises ValueError if not found."""
    candidates = discover_projects(config)
    for c in candidates:
        if c.name == name:
            return Path(c.path)
    available = ", ".join(p.name for p in candidates[:20])
    raise ValueError(f"project '{name}' not found. Available: {available}")
