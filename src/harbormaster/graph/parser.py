"""Per-language manifest parsers.

Each parser returns a `ProjectManifest` (or None if the file is
missing/unparseable) with a normalised shape:

  name        — canonical package name (composer's "vendor/pkg",
                npm's "name", Python's [project].name, Cargo's
                [package].name, Go's `module` directive)
  language    — string token from the supported set
  version     — best-effort string; None when the manifest has none
  description — best-effort string; None when missing
  deps        — direct runtime deps (no dev/test/peer)
  dev_deps    — dev / test / peer deps (kept separate so the graph
                can render or hide them)

`parse_project(path)` runs all parsers and returns the first hit. We
deliberately keep this best-effort: malformed JSON / TOML returns
None rather than raising, since a single broken manifest in one
project must not stop the rest of the graph from building.
"""
from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("harbormaster.graph.parser")

# Languages the parser recognises. Useful as a stable enum for the UI.
SUPPORTED_LANGUAGES = ("python", "javascript", "php", "rust", "go")


@dataclass(frozen=True)
class ProjectManifest:
    """Normalised view of one project's manifest file."""

    name: str
    language: str
    path: str
    manifest_file: str  # absolute path to the parsed file
    version: str | None = None
    description: str | None = None
    deps: tuple[str, ...] = field(default_factory=tuple)
    dev_deps: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        # tuples → lists for JSON
        d["deps"] = list(self.deps)
        d["dev_deps"] = list(self.dev_deps)
        return d


# --- per-language parsers -------------------------------------------------


def parse_pyproject_toml(path: Path) -> ProjectManifest | None:
    """Parse a Python project's pyproject.toml. Supports PEP 621
    `[project]` tables; falls back to `[tool.poetry]` for older
    Poetry projects."""
    manifest = path / "pyproject.toml"
    if not manifest.is_file():
        return None
    try:
        with manifest.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("pyproject.toml parse failed for %s: %s", path, e)
        return None

    proj = data.get("project") or {}
    name = proj.get("name")
    deps_raw = proj.get("dependencies") or []
    optional = proj.get("optional-dependencies") or {}
    dev_deps_raw = list(optional.get("dev", []))
    for k, v in optional.items():
        if k != "dev":
            dev_deps_raw.extend(v)
    description = proj.get("description")
    version = proj.get("version")

    if not name:
        # Poetry fallback
        poetry = data.get("tool", {}).get("poetry") or {}
        name = poetry.get("name")
        deps_raw = list((poetry.get("dependencies") or {}).keys())
        dev_deps_raw = list((poetry.get("dev-dependencies") or {}).keys())
        description = description or poetry.get("description")
        version = version or poetry.get("version")

    if not name:
        return None

    return ProjectManifest(
        name=str(name),
        language="python",
        path=str(path),
        manifest_file=str(manifest),
        version=str(version) if version else None,
        description=str(description) if description else None,
        deps=tuple(_strip_pep508_specifiers(d) for d in deps_raw if d),
        dev_deps=tuple(_strip_pep508_specifiers(d) for d in dev_deps_raw if d),
    )


def parse_package_json(path: Path) -> ProjectManifest | None:
    """Parse a JS/TS project's package.json."""
    manifest = path / "package.json"
    if not manifest.is_file():
        return None
    try:
        with manifest.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("package.json parse failed for %s: %s", path, e)
        return None

    name = data.get("name")
    if not name:
        return None

    deps = tuple((data.get("dependencies") or {}).keys())
    dev_deps = tuple(
        list((data.get("devDependencies") or {}).keys())
        + list((data.get("peerDependencies") or {}).keys())
    )

    return ProjectManifest(
        name=str(name),
        language="javascript",
        path=str(path),
        manifest_file=str(manifest),
        version=str(data["version"]) if data.get("version") else None,
        description=str(data["description"]) if data.get("description") else None,
        deps=deps,
        dev_deps=dev_deps,
    )


def parse_composer_json(path: Path) -> ProjectManifest | None:
    """Parse a PHP project's composer.json."""
    manifest = path / "composer.json"
    if not manifest.is_file():
        return None
    try:
        with manifest.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("composer.json parse failed for %s: %s", path, e)
        return None

    name = data.get("name")
    if not name:
        return None

    require = data.get("require") or {}
    require_dev = data.get("require-dev") or {}
    # Drop the `php` and `ext-*` pseudo-deps — they aren't packages.
    deps = tuple(k for k in require if k != "php" and not k.startswith("ext-"))
    dev_deps = tuple(k for k in require_dev if k != "php" and not k.startswith("ext-"))

    return ProjectManifest(
        name=str(name),
        language="php",
        path=str(path),
        manifest_file=str(manifest),
        version=str(data["version"]) if data.get("version") else None,
        description=str(data["description"]) if data.get("description") else None,
        deps=deps,
        dev_deps=dev_deps,
    )


def parse_cargo_toml(path: Path) -> ProjectManifest | None:
    """Parse a Rust project's Cargo.toml."""
    manifest = path / "Cargo.toml"
    if not manifest.is_file():
        return None
    try:
        with manifest.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("Cargo.toml parse failed for %s: %s", path, e)
        return None

    pkg = data.get("package") or {}
    name = pkg.get("name")
    if not name:
        return None

    deps = tuple((data.get("dependencies") or {}).keys())
    dev_deps = tuple(
        list((data.get("dev-dependencies") or {}).keys())
        + list((data.get("build-dependencies") or {}).keys())
    )

    return ProjectManifest(
        name=str(name),
        language="rust",
        path=str(path),
        manifest_file=str(manifest),
        version=str(pkg["version"]) if pkg.get("version") else None,
        description=str(pkg["description"]) if pkg.get("description") else None,
        deps=deps,
        dev_deps=dev_deps,
    )


_GO_MOD_MODULE_RE = re.compile(r"^\s*module\s+(\S+)", re.MULTILINE)
_GO_MOD_REQUIRE_BLOCK_RE = re.compile(
    r"^require\s*\((.*?)^\)", re.MULTILINE | re.DOTALL
)
_GO_MOD_REQUIRE_LINE_RE = re.compile(r"^\s*require\s+(\S+)\s+", re.MULTILINE)


def parse_go_mod(path: Path) -> ProjectManifest | None:
    """Parse a Go project's go.mod (no full lex; just enough for the
    `module` directive + direct `require` lines / blocks)."""
    manifest = path / "go.mod"
    if not manifest.is_file():
        return None
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError as e:
        logger.debug("go.mod read failed for %s: %s", path, e)
        return None

    m = _GO_MOD_MODULE_RE.search(text)
    if not m:
        return None
    name = m.group(1)

    deps_set: set[str] = set()
    for block in _GO_MOD_REQUIRE_BLOCK_RE.finditer(text):
        for line in block.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.endswith("// indirect"):
                continue
            tokens = line.split()
            if tokens:
                deps_set.add(tokens[0])
    for m2 in _GO_MOD_REQUIRE_LINE_RE.finditer(text):
        deps_set.add(m2.group(1))

    return ProjectManifest(
        name=name,
        language="go",
        path=str(path),
        manifest_file=str(manifest),
        deps=tuple(sorted(deps_set)),
    )


# Order matters: pyproject is preferred over package.json for repos
# that ship both (the Python project usually drives the language tag).
# Composer comes after pyproject because some Python repos drop a stub
# composer.json for editor tooling but aren't PHP projects.
_PARSERS = (
    parse_pyproject_toml,
    parse_package_json,
    parse_composer_json,
    parse_cargo_toml,
    parse_go_mod,
)


def parse_project(path: Path) -> ProjectManifest | None:
    """Try each known manifest format. Returns the first that parses
    successfully, or None when no manifest is present."""
    for parser in _PARSERS:
        result = parser(path)
        if result is not None:
            return result
    return None


# --- internal -----------------------------------------------------------

_PEP508_SPLIT_RE = re.compile(r"[<>=!~\s\[;]")


def _strip_pep508_specifiers(spec: str) -> str:
    """Reduce a PEP 508 requirement string ('foo>=1.2,<2; python_version > "3.10"')
    down to just the package name ('foo'). Non-canonical but enough for graph
    edges where we only care about which package a project depends on."""
    return _PEP508_SPLIT_RE.split(spec, 1)[0].strip()
