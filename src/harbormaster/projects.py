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
from concurrent.futures import ThreadPoolExecutor
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
    # v6.0.0a3: detected language ("python" / "javascript" / "php" /
    # "rust" / "go") from the project's manifest file, or "unknown" when
    # no recognised manifest is present. Drives the dashboard "group by
    # language" toggle.
    language: str = "unknown"
    # v9.0.0a6: integer days since `last_commit['date']`. Drives the
    # sidebar "Archived" group (>= 90 days). None when last_commit is
    # absent (no git history). Computed once at discovery time so the
    # frontend doesn't need to reparse the ISO date.
    last_commit_age_days: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_project(p: Path) -> bool:
    return p.is_dir() and ((p / ".git").is_dir() or (p / "CLAUDE.md").is_file())


def _detect_language(project_path: Path) -> str:
    """v6.0.0a3: best-effort language detection from manifest presence.

    Reuses the parser registry from harbormaster.graph.parser when
    available; falls back to file-existence checks. Returns "unknown"
    when no recognised manifest is present (e.g. docs-only repos).

    v21.0.0a9: when manifest + file-existence both fail, sample
    file extensions (linguist-style) before giving up.
    """
    try:
        from harbormaster.graph.parser import parse_project

        manifest = parse_project(project_path)
        if manifest is not None:
            return manifest.language
    except Exception:  # noqa: BLE001 - never block discovery on parser fail
        pass
    # Lightweight fallback for repos that have a recognisable marker
    # but the manifest itself fails to parse (broken JSON, etc.).
    if (project_path / "pyproject.toml").is_file() or \
            (project_path / "requirements.txt").is_file():
        return "python"
    if (project_path / "package.json").is_file():
        return "javascript"
    if (project_path / "composer.json").is_file():
        return "php"
    if (project_path / "Cargo.toml").is_file():
        return "rust"
    if (project_path / "go.mod").is_file():
        return "go"
    # v21.0.0a9: linguist-style extension sampling as the last resort.
    # Caps scan at 200 files so a huge monorepo without a manifest
    # doesn't tank discovery.
    ext_lang = _detect_language_from_extensions(project_path)
    if ext_lang is not None:
        return ext_lang
    return "unknown"


# v21.0.0a9: ext → language map shared across the linguist fallback.
# `None` means "doc/text — don't count toward majority".
_EXT_TO_LANG: dict[str, str | None] = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".php": "php",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".c": "c", ".h": "c",
    ".cs": "csharp",
    ".lua": "lua",
    ".sh": "shell", ".bash": "shell",
    ".md": None,  # docs don't define language
    ".txt": None,
}

_LINGUIST_SKIP_DIRS = {"node_modules", "vendor", "__pycache__", "dist", "build"}


def _detect_language_from_extensions(
    project_path: Path, max_files: int = 200,
) -> str | None:
    """v21.0.0a9: linguist-style fallback — count file extensions, majority wins.

    Only used when manifest-based detection returns nothing. Caps the
    scan at `max_files` files so a docs-only mega-repo without a
    manifest doesn't pay a multi-second walk.

    Skips hidden directories (`.git`, `.venv`, `.serena`, …) and a
    small set of dependency / build dirs (`node_modules`, `vendor`,
    `__pycache__`, `dist`, `build`).

    Returns None when no recognised source files are present.
    Ties are broken alphabetically so the result is deterministic.
    """
    counter: dict[str, int] = {}
    count = 0
    try:
        iterator = project_path.rglob("*")
    except OSError:
        return None
    for entry in iterator:
        if count >= max_files:
            break
        # Skip hidden dirs (.git, .venv, .serena, .pytest_cache, etc.)
        # plus dependency / build dirs. We test path *parts* relative
        # to the project root so a project under e.g. /home/.config/foo
        # still gets scanned.
        try:
            rel_parts = entry.relative_to(project_path).parts
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel_parts):
            continue
        if any(part in _LINGUIST_SKIP_DIRS for part in rel_parts):
            continue
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        lang = _EXT_TO_LANG.get(entry.suffix.lower())
        if lang:
            counter[lang] = counter.get(lang, 0) + 1
            count += 1
    if not counter:
        return None
    max_count = max(counter.values())
    winners = sorted(lang for lang, c in counter.items() if c == max_count)
    return winners[0]


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


def _matches_ignore_patterns(path: Path, patterns: list[str]) -> bool:
    """v10.0.0a4: glob-match the project basename + full path against
    every pattern in `[ignore].patterns`.

    Distinct semantics from `_is_excluded`:
      - patterns are ALWAYS fnmatched (no gitignore-style component
        shortcut; `node_modules` won't auto-match a path component).
      - The basename (`path.name`) is checked first; that's the
        common case for project-name globs like `*-ui` or `*-archive`.
      - Then the full string path, so absolute patterns
        `/full/path/*` still work.
      - `**/segment/**` is normalized so the `segment` part fnmatches
        each path component too — letting operators write
        `**/config-only/**` and have it hide projects under any
        `config-only` directory.
    """
    if not patterns:
        return False
    name = path.name
    s = str(path)
    parts = path.parts
    for raw in patterns:
        if not raw:
            continue
        if fnmatch.fnmatchcase(name, raw):
            return True
        if fnmatch.fnmatchcase(s, raw):
            return True
        if raw.startswith("**/") and raw.endswith("/**"):
            core = raw[3:-3]
            if core and any(fnmatch.fnmatchcase(p, core) for p in parts):
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


def _commit_age_days(last_commit: dict[str, str] | None) -> int | None:
    """v9.0.0a6: integer days since the last commit's ISO date.

    Returns None when last_commit is missing or its `date` field is
    malformed. Pure stdlib (datetime.fromisoformat handles `%cI`'s
    `2026-05-10T14:23:45+00:00` shape on Python 3.11+).
    """
    if not last_commit:
        return None
    iso = last_commit.get("date")
    if not iso:
        return None
    from datetime import UTC, datetime

    try:
        commit_dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    now = datetime.now(tz=UTC)
    if commit_dt.tzinfo is None:
        # Naive datetimes from %cI are unusual but defend anyway.
        commit_dt = commit_dt.replace(tzinfo=UTC)
    delta = now - commit_dt
    return max(0, delta.days)


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


def find_project_path(
    name: str,
    config: ProjectsConfig,
    *,
    ignore_patterns: list[str] | None = None,
) -> Path:
    """Fast project-by-name lookup. No git, no rich metadata, no sort.

    Walks configured globs and returns the first match whose directory name
    equals `name` and which passes the containment + exclude + ignore
    filters. Validates `name` against the strict regex first.

    `ignore_patterns` (v10.0.0a4) are top-level `[ignore].patterns`
    from HarbormasterConfig; default `None` keeps the v9 contract for
    callers that haven't been updated yet.
    """
    validate_project_name(name)
    bases_with_matches = _iter_glob_matches(config)
    bases = [b for b, _ in bases_with_matches if str(b) != "/"]
    ignore = ignore_patterns or []

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
            if _matches_ignore_patterns(resolved, ignore):
                continue
            if bases and not _is_under_any_base(resolved, bases):
                continue
            if config.require_marker and not (resolved / "CLAUDE.md").is_file() \
                    and not (resolved / ".serena").is_dir():
                continue
            return resolved

    raise ValueError(f"project {name!r} not found in configured globs")


def discover_projects(
    config: ProjectsConfig,
    *,
    ignore_patterns: list[str] | None = None,
) -> list[ProjectInfo]:
    """Walk configured globs and return rich ProjectInfo for every match.

    Sorted by last commit date desc. Pays one `git log` subprocess per match —
    use this for the list_projects MCP tool, NOT for hot lookup paths.

    `ignore_patterns` (v10.0.0a4) are top-level `[ignore].patterns`
    from HarbormasterConfig; default `None` keeps the v9 contract for
    callers that haven't been updated yet.
    """
    bases_with_matches = _iter_glob_matches(config)
    bases = [b for b, _ in bases_with_matches if str(b) != "/"]
    seen: set[Path] = set()
    eligible: list[Path] = []
    ignore = ignore_patterns or []

    # Phase 1: filter eligible project paths (cheap predicate checks).
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
            if _matches_ignore_patterns(resolved, ignore):
                continue
            if bases and not _is_under_any_base(resolved, bases):
                continue
            if config.require_marker and not (resolved / "CLAUDE.md").is_file() \
                    and not (resolved / ".serena").is_dir():
                continue
            seen.add(resolved)
            eligible.append(resolved)

    # Phase 2: build ProjectInfo per path in parallel. The per-path work
    # is dominated by two slow operations:
    #   - `_git_last_commit` spawns a `git log` subprocess (~14 ms each).
    #   - `_detect_language` may run a pathlib.rglob fallback (~90 ms each
    #     for projects without a recognisable manifest).
    # Both release the GIL during the syscalls, so a ThreadPoolExecutor
    # gives near-linear speedup. v21.0.3 perf: ~1.6 s → ~150 ms for a
    # 62-project workspace (16-wide pool, see docs/perf-deep-dive).
    def _build_info(resolved: Path) -> ProjectInfo:
        last_commit = _git_last_commit(resolved)
        return ProjectInfo(
            name=resolved.name,
            path=str(resolved),
            last_commit=last_commit,
            has_serena=(resolved / ".serena").is_dir(),
            has_claude_md=(resolved / "CLAUDE.md").is_file(),
            brief=_project_brief(resolved),
            language=_detect_language(resolved),
            last_commit_age_days=_commit_age_days(last_commit),
        )

    projects: list[ProjectInfo] = []
    if eligible:
        max_workers = min(16, len(eligible))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            projects = list(pool.map(_build_info, eligible))

    projects.sort(
        key=lambda p: p.last_commit["date"] if p.last_commit else "",
        reverse=True,
    )
    return projects


def resolve_project(
    name: str,
    config: ProjectsConfig,
    *,
    ignore_patterns: list[str] | None = None,
) -> Path:
    """Public API: return the path of a project by name.

    Now an alias for find_project_path — kept under the original name to
    preserve external API stability. Callers that need rich metadata should
    use discover_projects() and filter on .name.

    `ignore_patterns` (v10.0.0a4) is plumbed through to find_project_path.
    """
    return find_project_path(name, config, ignore_patterns=ignore_patterns)
