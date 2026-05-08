"""Unit tests for project discovery, name validation, and traversal guards."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import ProjectsConfig
from harbormaster.projects import (
    discover_projects,
    resolve_project,
    validate_project_name,
)

# ----- validate_project_name -------------------------------------------------


@pytest.mark.parametrize("good", ["pinporn", "my-project", "client_1.2", "Project99", "a", "harbormaster"])
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
