"""Unit tests for project discovery, name validation, and traversal guards."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import ProjectsConfig
from harbormaster.projects import (
    discover_projects,
    find_project_path,
    resolve_project,
    validate_project_name,
)

# ----- validate_project_name -------------------------------------------------


@pytest.mark.parametrize("good", ["accounting-fleetq", "my-project", "client_1.2", "Project99", "a", "harbormaster"])
def test_validate_project_name_accepts_safe_names(good):
    validate_project_name(good)  # should not raise


@pytest.mark.parametrize(
    "bad",
    [
        "",
        ".",
        "..",
        "../etc",
        "../../etc/passwd",
        "/etc/passwd",
        "foo/bar",
        ".hidden",
        "name with space",
        "name;rm -rf /",
        "name$(whoami)",
        "name`id`",
        "name|pipe",
        "name\nnewline",
        "name\x00null",
    ],
)
def test_validate_project_name_rejects_unsafe(bad):
    with pytest.raises(ValueError, match="invalid project name"):
        validate_project_name(bad)


# ----- resolve_project rejects traversal before disk walk -------------------


def test_resolve_project_rejects_traversal_immediately():
    cfg = ProjectsConfig(glob=["~/htdocs/*"])
    with pytest.raises(ValueError, match="invalid project name"):
        resolve_project("..", cfg)
    with pytest.raises(ValueError, match="invalid project name"):
        resolve_project("../etc", cfg)


def test_resolve_project_rejects_unknown_real_name():
    """Valid name shape but no such project on disk — distinct from the
    invalid-name path. Underscore-leading names are rejected by the regex,
    so use a hyphen-leading name (still safe, just doesn't exist)."""
    cfg = ProjectsConfig(glob=["~/htdocs/*"])
    with pytest.raises(ValueError, match="not found"):
        resolve_project("definitely-not-a-real-project-zzz", cfg)


# ----- discover_projects containment ----------------------------------------


def _make_project_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / "CLAUDE.md").write_text("# test", encoding="utf-8")


def test_discover_projects_finds_simple_glob(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "alpha")
    _make_project_dir(base / "beta")
    cfg = ProjectsConfig(glob=[f"{base}/*"])
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert {"alpha", "beta"} <= names


def test_discover_projects_skips_symlink_outside_base(tmp_path: Path):
    """Symlink under the configured base pointing outside is skipped — would
    otherwise be a traversal-via-discovery vector (resolved to /etc/...)."""
    base = tmp_path / "code"
    base.mkdir()
    outside = tmp_path / "outside"
    _make_project_dir(outside / "secret-project")  # has CLAUDE.md → looks like a project
    # Create a symlink inside base that points to outside/secret-project
    (base / "evil").symlink_to(outside / "secret-project")
    cfg = ProjectsConfig(glob=[f"{base}/*"])
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "secret-project" not in names
    assert "evil" not in names


def test_discover_projects_respects_exclude(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "real")
    _make_project_dir(base / "node_modules")
    cfg = ProjectsConfig(glob=[f"{base}/*"], exclude=["node_modules"])
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "real" in names
    assert "node_modules" not in names


def test_discover_projects_require_marker(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "with-claude")  # has CLAUDE.md
    (base / "git-only").mkdir(parents=True)
    (base / "git-only" / ".git").mkdir()  # has .git but no CLAUDE.md / .serena
    cfg = ProjectsConfig(glob=[f"{base}/*"], require_marker=True)
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "with-claude" in names
    assert "git-only" not in names  # require_marker filters it out


# ----- config-driven base resolution -----------------------------------------


def test_resolve_project_under_configured_base(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "myproj")
    cfg = ProjectsConfig(glob=[f"{base}/*"])
    p = resolve_project("myproj", cfg)
    assert p == (base / "myproj").resolve()


# ----- find_project_path (cheap lookup, no git spawns) -----------------------


def test_find_project_path_returns_path(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "myproj")
    cfg = ProjectsConfig(glob=[f"{base}/*"])
    p = find_project_path("myproj", cfg)
    assert p == (base / "myproj").resolve()


def test_find_project_path_validates_name():
    cfg = ProjectsConfig(glob=["~/htdocs/*"])
    with pytest.raises(ValueError, match="invalid project name"):
        find_project_path("..", cfg)


def test_find_project_path_raises_on_unknown(tmp_path: Path):
    cfg = ProjectsConfig(glob=[f"{tmp_path}/*"])
    with pytest.raises(ValueError, match="not found"):
        find_project_path("nonexistent-project-xyz", cfg)


def test_find_project_path_respects_containment(tmp_path: Path):
    """Symlink under base pointing to a 'project' outside should not be
    findable — same containment guard as discover_projects."""
    base = tmp_path / "code"
    base.mkdir()
    outside = tmp_path / "outside"
    _make_project_dir(outside / "secret")
    (base / "secret").symlink_to(outside / "secret")
    cfg = ProjectsConfig(glob=[f"{base}/*"])
    with pytest.raises(ValueError, match="not found"):
        find_project_path("secret", cfg)


# ----- gitignore-style excludes ---------------------------------------------


def test_excludes_double_star_node_modules(tmp_path: Path):
    """`**/node_modules/**` should exclude any project whose path contains
    a `node_modules` component, regardless of depth."""
    base = tmp_path / "code"
    _make_project_dir(base / "real")
    deep = base / "monorepo" / "node_modules" / "leaked"
    _make_project_dir(deep)
    cfg = ProjectsConfig(
        glob=[f"{base}/**/*"],
        exclude=["**/node_modules/**"],
    )
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "real" in names
    assert "leaked" not in names


def test_excludes_glob_pattern(tmp_path: Path):
    """`test_fixture_*` should exclude matching path components via fnmatch."""
    base = tmp_path / "code"
    _make_project_dir(base / "real")
    _make_project_dir(base / "test_fixture_x")
    cfg = ProjectsConfig(glob=[f"{base}/*"], exclude=["test_fixture_*"])
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "real" in names
    assert "test_fixture_x" not in names


# ----- recursive ** glob ------------------------------------------------------


def test_recursive_glob_finds_deeply_nested(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "a" / "deep" / "nested" / "proj")
    cfg = ProjectsConfig(glob=[f"{base}/**/*"])
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "proj" in names


def test_recursive_glob_exclude_filters_inside(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "good")
    _make_project_dir(base / "vendor" / "thirdparty" / "lib")
    cfg = ProjectsConfig(
        glob=[f"{base}/**/*"],
        exclude=["**/vendor/**"],
    )
    projects = discover_projects(cfg)
    names = {p.name for p in projects}
    assert "good" in names
    assert "lib" not in names
    assert "vendor" not in names
