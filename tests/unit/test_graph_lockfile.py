"""Tests for harbormaster.graph.lockfile per-language lockfile parsers (v2.0.0a1)."""
from __future__ import annotations

import json
from pathlib import Path

from harbormaster.graph.lockfile import (
    LOCKFILE_CANDIDATES,
    find_lockfile,
    parse_cargo_lock,
    parse_composer_lock,
    parse_go_sum,
    parse_lockfile,
    parse_package_lock_json,
    parse_pnpm_lock,
    parse_poetry_lock,
    parse_requirements_txt,
    parse_uv_lock,
    parse_yarn_lock,
)

# --- uv.lock --------------------------------------------------------------


def test_uv_lock_basic(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(
        'version = 1\n'
        '\n'
        '[[package]]\n'
        'name = "click"\n'
        'version = "8.1.7"\n'
        '\n'
        '[[package]]\n'
        'name = "rich"\n'
        'version = "13.7.0"\n'
    )
    pkgs = parse_uv_lock(tmp_path / "uv.lock")
    assert pkgs == {"click", "rich"}


def test_uv_lock_missing_returns_none(tmp_path: Path) -> None:
    assert parse_uv_lock(tmp_path / "uv.lock") is None


def test_uv_lock_malformed_returns_none(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("not [valid toml")
    assert parse_uv_lock(tmp_path / "uv.lock") is None


# --- poetry.lock ----------------------------------------------------------


def test_poetry_lock_basic(tmp_path: Path) -> None:
    (tmp_path / "poetry.lock").write_text(
        '[[package]]\n'
        'name = "flask"\n'
        'version = "3.0.0"\n'
        '\n'
        '[[package]]\n'
        'name = "werkzeug"\n'
        'version = "3.0.1"\n'
    )
    pkgs = parse_poetry_lock(tmp_path / "poetry.lock")
    assert pkgs == {"flask", "werkzeug"}


def test_poetry_lock_missing_returns_none(tmp_path: Path) -> None:
    assert parse_poetry_lock(tmp_path / "poetry.lock") is None


# --- requirements.txt -----------------------------------------------------


def test_requirements_txt_basic(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        '# my deps\n'
        '\n'
        'requests>=2.31.0\n'
        'click==8.1.7\n'
        'pydantic ~= 2.5; python_version >= "3.10"\n'
        '-r other.txt\n'
        'rich  # optional\n'
    )
    pkgs = parse_requirements_txt(tmp_path / "requirements.txt")
    assert pkgs == {"requests", "click", "pydantic", "rich"}


def test_requirements_txt_skips_blanks_and_comments(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("\n# only comment\n   \n")
    pkgs = parse_requirements_txt(tmp_path / "requirements.txt")
    assert pkgs == set()


# --- package-lock.json (npm v2/v3) ---------------------------------------


def test_package_lock_json_v3_packages_block(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "my-app",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "my-app", "dependencies": {}},
                    "node_modules/react": {"version": "18.2.0"},
                    "node_modules/@scope/pkg": {"version": "1.0.0"},
                    "node_modules/lodash/node_modules/baz": {"version": "1.0.0"},
                },
            }
        )
    )
    pkgs = parse_package_lock_json(tmp_path / "package-lock.json")
    assert pkgs == {"react", "@scope/pkg", "baz"}


def test_package_lock_json_v1_dependencies_block(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "old-app",
                "lockfileVersion": 1,
                "dependencies": {
                    "lodash": {"version": "4.17.21"},
                    "@scope/inner": {
                        "version": "2.0.0",
                        "dependencies": {"transitive": {"version": "1.0.0"}},
                    },
                },
            }
        )
    )
    pkgs = parse_package_lock_json(tmp_path / "package-lock.json")
    assert pkgs == {"lodash", "@scope/inner", "transitive"}


# --- composer.lock --------------------------------------------------------


def test_composer_lock_basic(tmp_path: Path) -> None:
    (tmp_path / "composer.lock").write_text(
        json.dumps(
            {
                "packages": [{"name": "laravel/framework"}, {"name": "monolog/monolog"}],
                "packages-dev": [{"name": "phpunit/phpunit"}],
            }
        )
    )
    pkgs = parse_composer_lock(tmp_path / "composer.lock")
    assert pkgs == {"laravel/framework", "monolog/monolog", "phpunit/phpunit"}


# --- Cargo.lock -----------------------------------------------------------


def test_cargo_lock_basic(tmp_path: Path) -> None:
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\n'
        'name = "serde"\n'
        'version = "1.0.0"\n'
        '\n'
        '[[package]]\n'
        'name = "tokio"\n'
        'version = "1.30.0"\n'
    )
    pkgs = parse_cargo_lock(tmp_path / "Cargo.lock")
    assert pkgs == {"serde", "tokio"}


# --- go.sum --------------------------------------------------------------


def test_go_sum_basic(tmp_path: Path) -> None:
    (tmp_path / "go.sum").write_text(
        'github.com/stretchr/testify v1.9.0 h1:abcd\n'
        'github.com/stretchr/testify v1.9.0/go.mod h1:efgh\n'
        'golang.org/x/sync v0.7.0 h1:ijkl\n'
    )
    pkgs = parse_go_sum(tmp_path / "go.sum")
    assert pkgs == {"github.com/stretchr/testify", "golang.org/x/sync"}


# --- find_lockfile / parse_lockfile dispatcher ---------------------------


def test_find_lockfile_uv_wins_over_poetry(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("[[package]]\nname='a'\nversion='1'\n")
    (tmp_path / "poetry.lock").write_text("[[package]]\nname='b'\nversion='2'\n")
    found = find_lockfile(tmp_path, "python")
    assert found is not None
    assert found.name == "uv.lock"


def test_find_lockfile_returns_none_when_absent(tmp_path: Path) -> None:
    assert find_lockfile(tmp_path, "python") is None


def test_find_lockfile_unknown_language_returns_none(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("[[package]]\nname='a'\nversion='1'\n")
    assert find_lockfile(tmp_path, "haskell") is None


def test_parse_lockfile_returns_path_and_packages(tmp_path: Path) -> None:
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "serde"\nversion = "1"\n'
    )
    result = parse_lockfile(tmp_path, "rust")
    assert result is not None
    lockfile_path, pkgs = result
    assert lockfile_path == tmp_path / "Cargo.lock"
    assert pkgs == {"serde"}


def test_parse_lockfile_returns_none_when_no_match(tmp_path: Path) -> None:
    assert parse_lockfile(tmp_path, "python") is None


def test_lockfile_candidates_covers_supported_languages() -> None:
    """Every supported language MUST have at least one lockfile candidate
    so `parse_lockfile` doesn't silently no-op for valid manifests."""
    assert set(LOCKFILE_CANDIDATES.keys()) == {
        "python",
        "javascript",
        "php",
        "rust",
        "go",
    }


# --- pnpm-lock.yaml -------------------------------------------------------


def test_pnpm_lock_v6_format(tmp_path: Path) -> None:
    """pnpm v6 lockfile uses /name@version keys with optional leading slash."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '6.0'\n"
        "\n"
        "packages:\n"
        "  /react@18.2.0:\n"
        "    resolution: {integrity: sha512-...}\n"
        "    dev: false\n"
        "  /lodash@4.17.21:\n"
        "    resolution: {integrity: sha512-...}\n"
    )
    pkgs = parse_pnpm_lock(tmp_path / "pnpm-lock.yaml")
    assert pkgs == {"react", "lodash"}


def test_pnpm_lock_scoped_packages(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text(
        "packages:\n"
        "  /@types/node@20.10.0:\n"
        "    resolution: {integrity: sha512-...}\n"
        "  '/@types/react@18.2.0':\n"
        "    resolution: {integrity: sha512-...}\n"
    )
    pkgs = parse_pnpm_lock(tmp_path / "pnpm-lock.yaml")
    assert pkgs == {"@types/node", "@types/react"}


def test_pnpm_lock_v9_format_no_leading_slash(tmp_path: Path) -> None:
    """pnpm v9+ drops the leading slash."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n"
        "\n"
        "packages:\n"
        "  react@18.2.0:\n"
        "    resolution: {integrity: sha512-...}\n"
        "  '@types/node@20.10.0':\n"
        "    resolution: {integrity: sha512-...}\n"
    )
    pkgs = parse_pnpm_lock(tmp_path / "pnpm-lock.yaml")
    assert pkgs == {"react", "@types/node"}


def test_pnpm_lock_ignores_deeper_indents(tmp_path: Path) -> None:
    """Resolution / dependencies blocks use 4+ space indent — they must NOT
    be treated as package keys."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        "packages:\n"
        "  /react@18.2.0:\n"
        "    resolution: {integrity: sha512-...}\n"
        "    dependencies:\n"
        "      loose-envify: 1.4.0\n"
    )
    pkgs = parse_pnpm_lock(tmp_path / "pnpm-lock.yaml")
    assert pkgs == {"react"}


def test_pnpm_lock_stops_at_dedent(tmp_path: Path) -> None:
    """A new top-level section after `packages:` must not be parsed."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        "packages:\n"
        "  /react@18.2.0:\n"
        "    resolution: {integrity: sha512-...}\n"
        "snapshots:\n"
        "  /lodash@4.17.21:\n"
        "    resolution: {integrity: sha512-...}\n"
    )
    pkgs = parse_pnpm_lock(tmp_path / "pnpm-lock.yaml")
    assert pkgs == {"react"}


def test_pnpm_lock_missing_returns_none(tmp_path: Path) -> None:
    assert parse_pnpm_lock(tmp_path / "pnpm-lock.yaml") is None


def test_pnpm_lock_empty_packages_returns_none(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '6.0'\n"
        "packages: {}\n"
    )
    assert parse_pnpm_lock(tmp_path / "pnpm-lock.yaml") is None


# --- yarn.lock ------------------------------------------------------------


def test_yarn_lock_v1_basic(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text(
        "# THIS FILE IS GENERATED, DO NOT EDIT\n"
        "\n"
        '"@types/node@^20.0.0":\n'
        '  version "20.10.0"\n'
        '  resolved "..."\n'
        "\n"
        '"react@^18.0.0":\n'
        '  version "18.2.0"\n'
    )
    pkgs = parse_yarn_lock(tmp_path / "yarn.lock")
    assert pkgs == {"@types/node", "react"}


def test_yarn_lock_v1_multiple_selectors(tmp_path: Path) -> None:
    """yarn allows comma-separated selectors sharing one resolved entry."""
    (tmp_path / "yarn.lock").write_text(
        '"react@^18.0.0", "react@^18.2.0", "react@~18.2.0":\n'
        '  version "18.2.0"\n'
    )
    pkgs = parse_yarn_lock(tmp_path / "yarn.lock")
    assert pkgs == {"react"}


def test_yarn_lock_unquoted_selectors(tmp_path: Path) -> None:
    """yarn v1 allows unquoted selectors when no special chars are present."""
    (tmp_path / "yarn.lock").write_text(
        "react@18.0.0:\n"
        '  version "18.0.0"\n'
    )
    pkgs = parse_yarn_lock(tmp_path / "yarn.lock")
    assert pkgs == {"react"}


def test_yarn_lock_berry_format(tmp_path: Path) -> None:
    """yarn berry uses npm: prefix in the version spec."""
    (tmp_path / "yarn.lock").write_text(
        "# This file is generated by running \"yarn install\" inside your project.\n"
        "\n"
        "__metadata:\n"
        "  version: 6\n"
        "  cacheKey: 8\n"
        "\n"
        '"@types/node@npm:^20.0.0":\n'
        "  version: 20.10.0\n"
        "  resolution: \"@types/node@npm:20.10.0\"\n"
        "\n"
        '"react@npm:^18.2.0":\n'
        "  version: 18.2.0\n"
    )
    pkgs = parse_yarn_lock(tmp_path / "yarn.lock")
    assert pkgs == {"@types/node", "react"}


def test_yarn_lock_skips_metadata_block(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text(
        "__metadata:\n"
        "  version: 6\n"
        "\n"
        '"react@npm:^18.0.0":\n'
        "  version: 18.0.0\n"
    )
    pkgs = parse_yarn_lock(tmp_path / "yarn.lock")
    assert pkgs == {"react"}


def test_yarn_lock_missing_returns_none(tmp_path: Path) -> None:
    assert parse_yarn_lock(tmp_path / "yarn.lock") is None


def test_yarn_lock_only_comments_returns_none(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text(
        "# THIS FILE IS GENERATED\n"
        "# Do not edit\n"
    )
    assert parse_yarn_lock(tmp_path / "yarn.lock") is None


# --- precedence -----------------------------------------------------------


def test_javascript_finds_pnpm_when_npm_absent(tmp_path: Path) -> None:
    """If only pnpm-lock exists, find_lockfile should pick it (after npm)."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        "packages:\n"
        "  /react@18.2.0:\n"
        "    resolution: {integrity: sha512-...}\n"
    )
    found = find_lockfile(tmp_path, "javascript")
    assert found == tmp_path / "pnpm-lock.yaml"


def test_javascript_finds_yarn_when_only_yarn_present(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text(
        '"react@^18.0.0":\n'
        '  version "18.2.0"\n'
    )
    found = find_lockfile(tmp_path, "javascript")
    assert found == tmp_path / "yarn.lock"


def test_javascript_npm_takes_precedence_over_pnpm_and_yarn(tmp_path: Path) -> None:
    """Mono-repos with multiple lockfiles → npm wins (matches existing
    package-lock-first ordering)."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"name": "root", "lockfileVersion": 3, "packages": {
            "node_modules/react": {"version": "18.2.0"}
        }})
    )
    (tmp_path / "pnpm-lock.yaml").write_text(
        "packages:\n  /lodash@4.17.21:\n    resolution: {integrity: sha512-...}\n"
    )
    (tmp_path / "yarn.lock").write_text('"underscore@1":\n  version "1.0.0"\n')
    result = parse_lockfile(tmp_path, "javascript")
    assert result is not None
    lockfile_path, pkgs = result
    assert lockfile_path.name == "package-lock.json"
    # only react comes from package-lock; lodash + underscore must NOT leak in
    assert pkgs == {"react"}
