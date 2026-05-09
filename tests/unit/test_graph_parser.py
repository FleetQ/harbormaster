"""Tests for harbormaster.graph.parser per-language parsers."""
from __future__ import annotations

from pathlib import Path

from harbormaster.graph.parser import (
    SUPPORTED_LANGUAGES,
    parse_cargo_toml,
    parse_composer_json,
    parse_go_mod,
    parse_package_json,
    parse_project,
    parse_pyproject_toml,
)

# --- pyproject.toml -------------------------------------------------------


def test_pyproject_pep621_basic(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\n'
        'name = "myapp"\n'
        'version = "1.2.3"\n'
        'description = "An app."\n'
        'dependencies = ["requests>=2", "click ~=8.1"]\n'
        '\n'
        '[project.optional-dependencies]\n'
        'dev = ["pytest>=7"]\n'
        'docs = ["sphinx"]\n'
    )
    m = parse_pyproject_toml(tmp_path)
    assert m is not None
    assert m.name == "myapp"
    assert m.language == "python"
    assert m.version == "1.2.3"
    assert m.description == "An app."
    assert m.deps == ("requests", "click")
    assert "pytest" in m.dev_deps
    assert "sphinx" in m.dev_deps


def test_pyproject_poetry_fallback(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\n'
        'name = "legacy-app"\n'
        'version = "0.1.0"\n'
        '\n'
        '[tool.poetry.dependencies]\n'
        'python = "^3.10"\n'
        'flask = "^2"\n'
    )
    m = parse_pyproject_toml(tmp_path)
    assert m is not None
    assert m.name == "legacy-app"
    assert m.language == "python"
    assert "flask" in m.deps
    assert "python" in m.deps  # poetry includes python pseudo-dep — we keep it


def test_pyproject_returns_none_on_missing_file(tmp_path: Path):
    assert parse_pyproject_toml(tmp_path) is None


def test_pyproject_returns_none_on_malformed_toml(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("this is not [valid toml")
    assert parse_pyproject_toml(tmp_path) is None


def test_pyproject_returns_none_when_no_name(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nversion = '1'\n")
    assert parse_pyproject_toml(tmp_path) is None


# --- package.json ---------------------------------------------------------


def test_package_json_basic(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"name": "my-frontend", "version": "0.5.0", '
        '"description": "A web app.", '
        '"dependencies": {"react": "^18", "axios": "^1"}, '
        '"devDependencies": {"vitest": "^1"}, '
        '"peerDependencies": {"react-dom": "^18"}}'
    )
    m = parse_package_json(tmp_path)
    assert m is not None
    assert m.name == "my-frontend"
    assert m.language == "javascript"
    assert m.version == "0.5.0"
    assert set(m.deps) == {"react", "axios"}
    assert "vitest" in m.dev_deps
    assert "react-dom" in m.dev_deps


def test_package_json_returns_none_on_malformed(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": invalid json')
    assert parse_package_json(tmp_path) is None


# --- composer.json --------------------------------------------------------


def test_composer_json_basic(tmp_path: Path):
    (tmp_path / "composer.json").write_text(
        '{"name": "vendor/myapp", '
        '"description": "PHP project", '
        '"require": {"php": "^8.2", "ext-mbstring": "*", "laravel/framework": "^11"}, '
        '"require-dev": {"phpunit/phpunit": "^11"}}'
    )
    m = parse_composer_json(tmp_path)
    assert m is not None
    assert m.name == "vendor/myapp"
    assert m.language == "php"
    # php + ext-* should be filtered out
    assert m.deps == ("laravel/framework",)
    assert "phpunit/phpunit" in m.dev_deps


def test_composer_json_returns_none_when_no_name(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"require": {"foo/bar": "*"}}')
    assert parse_composer_json(tmp_path) is None


# --- Cargo.toml -----------------------------------------------------------


def test_cargo_toml_basic(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\n'
        'name = "rust-app"\n'
        'version = "0.1.0"\n'
        'description = "Rust thing"\n'
        '\n'
        '[dependencies]\n'
        'serde = "1"\n'
        'tokio = "1"\n'
        '\n'
        '[dev-dependencies]\n'
        'criterion = "0.5"\n'
    )
    m = parse_cargo_toml(tmp_path)
    assert m is not None
    assert m.name == "rust-app"
    assert m.language == "rust"
    assert set(m.deps) == {"serde", "tokio"}
    assert "criterion" in m.dev_deps


# --- go.mod ---------------------------------------------------------------


def test_go_mod_basic_with_require_block(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        'module github.com/me/myservice\n'
        '\n'
        'go 1.22\n'
        '\n'
        'require (\n'
        '    github.com/stretchr/testify v1.9.0\n'
        '    github.com/spf13/cobra v1.8.0 // indirect\n'
        '    golang.org/x/sync v0.7.0\n'
        ')\n'
    )
    m = parse_go_mod(tmp_path)
    assert m is not None
    assert m.name == "github.com/me/myservice"
    assert m.language == "go"
    assert "github.com/stretchr/testify" in m.deps
    assert "golang.org/x/sync" in m.deps
    # Indirect deps are skipped:
    assert "github.com/spf13/cobra" not in m.deps


def test_go_mod_basic_with_single_require_lines(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        'module example.com/svc\n'
        'go 1.21\n'
        'require github.com/google/uuid v1.6.0\n'
        'require github.com/pkg/errors v0.9.1\n'
    )
    m = parse_go_mod(tmp_path)
    assert m is not None
    assert m.name == "example.com/svc"
    assert "github.com/google/uuid" in m.deps
    assert "github.com/pkg/errors" in m.deps


def test_go_mod_returns_none_when_no_module_directive(tmp_path: Path):
    (tmp_path / "go.mod").write_text("go 1.22\n")
    assert parse_go_mod(tmp_path) is None


# --- parse_project (multi-format dispatcher) -----------------------------


def test_parse_project_returns_none_on_empty_dir(tmp_path: Path):
    assert parse_project(tmp_path) is None


def test_parse_project_picks_pyproject_when_both_present(tmp_path: Path):
    """Repos that ship both pyproject.toml + package.json (rare but
    real — e.g. Python lib with a docs site) should be classified as
    Python."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "polyglot"\nversion = "1"\n'
    )
    (tmp_path / "package.json").write_text('{"name": "polyglot-frontend"}')
    m = parse_project(tmp_path)
    assert m is not None
    assert m.name == "polyglot"
    assert m.language == "python"


def test_supported_languages_list_is_stable():
    assert SUPPORTED_LANGUAGES == ("python", "javascript", "php", "rust", "go")


# --- as_dict serialisation ----------------------------------------------


def test_manifest_as_dict_lists_deps(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["a", "b"]\n'
    )
    m = parse_pyproject_toml(tmp_path)
    assert m is not None
    d = m.as_dict()
    assert isinstance(d["deps"], list)
    assert d["deps"] == ["a", "b"]
