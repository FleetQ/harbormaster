"""v10.0.0a4: project ignore patterns.

`[ignore].patterns` is a top-level glob list applied at discovery
time. Tests pin:

  - `IgnoreConfig` default = empty patterns.
  - `discover_projects(... ignore_patterns=...)` filters out matching
    projects.
  - Glob shape: basename match, full-path match,
    `**/segment/**` component match.
  - `find_project_path` honors the same filter (raises ValueError
    on a name that's hidden).
  - Backward-compat: omitting `ignore_patterns` reproduces v9 behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import IgnoreConfig, ProjectsConfig
from harbormaster.projects import (
    _matches_ignore_patterns,
    discover_projects,
    find_project_path,
)


def _make_project_dir(parent: Path, name: str) -> Path:
    """Create a minimal project dir that satisfies _is_project()."""
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()  # `.git` makes _is_project return True
    return p


def test_ignore_config_default_is_empty() -> None:
    assert IgnoreConfig().patterns == []


def test_ignore_config_accepts_patterns() -> None:
    cfg = IgnoreConfig(patterns=["*-ui", "**/archive/**"])
    assert cfg.patterns == ["*-ui", "**/archive/**"]


def test_ignore_config_forbids_extra_keys() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        IgnoreConfig(patterns=[], unknown_key=True)  # type: ignore[call-arg]


# -- _matches_ignore_patterns helper ------------------------------------


def test_matches_basename_glob(tmp_path: Path) -> None:
    p = tmp_path / "foo-ui"
    assert _matches_ignore_patterns(p, ["*-ui"])
    assert not _matches_ignore_patterns(p, ["*-cli"])


def test_matches_full_path_glob(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nested" / "leaf"
    assert _matches_ignore_patterns(p, [str(tmp_path) + "/*/*/*"])


def test_matches_component_via_double_star(tmp_path: Path) -> None:
    p = tmp_path / "outer" / "config-only" / "inner"
    assert _matches_ignore_patterns(p, ["**/config-only/**"])


def test_no_match_returns_false_for_unrelated(tmp_path: Path) -> None:
    p = tmp_path / "regular-project"
    assert not _matches_ignore_patterns(p, ["*-ui", "**/archive/**"])


def test_empty_patterns_short_circuits(tmp_path: Path) -> None:
    p = tmp_path / "anything"
    assert not _matches_ignore_patterns(p, [])


# -- discover_projects integration --------------------------------------


def test_discover_projects_no_ignore_returns_all(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta-ui")
    cfg = ProjectsConfig(glob=[f"{tmp_path}/*"])
    names = sorted(p.name for p in discover_projects(cfg))
    assert names == ["alpha", "beta-ui"]


def test_discover_projects_filters_basename_glob(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta-ui")
    _make_project_dir(tmp_path, "gamma-ui")
    cfg = ProjectsConfig(glob=[f"{tmp_path}/*"])
    names = sorted(
        p.name for p in discover_projects(cfg, ignore_patterns=["*-ui"])
    )
    assert names == ["alpha"]


def test_discover_projects_filters_double_star_segment(tmp_path: Path) -> None:
    """`**/archive/**` hides any project under an `archive` directory."""
    _make_project_dir(tmp_path, "live-project")
    _make_project_dir(tmp_path / "archive", "old-project")
    cfg = ProjectsConfig(glob=[f"{tmp_path}/**"])
    names = sorted(
        p.name for p in discover_projects(cfg, ignore_patterns=["**/archive/**"])
    )
    assert names == ["live-project"]


def test_find_project_path_honors_ignore(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "foo-ui")
    cfg = ProjectsConfig(glob=[f"{tmp_path}/*"])
    # Without ignore: resolves.
    assert find_project_path("foo-ui", cfg).name == "foo-ui"
    # With ignore: raises.
    with pytest.raises(ValueError, match="not found"):
        find_project_path("foo-ui", cfg, ignore_patterns=["*-ui"])


def test_discover_projects_backward_compat_no_ignore_kwarg(tmp_path: Path) -> None:
    """v9 callers that don't pass ignore_patterns get unchanged behaviour."""
    _make_project_dir(tmp_path, "alpha")
    cfg = ProjectsConfig(glob=[f"{tmp_path}/*"])
    names = sorted(p.name for p in discover_projects(cfg))
    assert names == ["alpha"]
