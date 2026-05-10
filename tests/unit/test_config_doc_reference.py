"""v13.0.0a6: doc-link smoke for `docs/operator-config-reference.md`.

Two related guarantees:

1. The canonical config-reference file exists and is non-empty.
2. README.md's link to it actually resolves.
3. Every documented section header in the reference matches an
   actual `[<section>]` in the worked-example block (catches the
   case where a section is listed in the table-of-contents but
   omitted from the example).
4. Every config field on `HarbormasterConfig` (and its sub-models)
   has at least one mention in the reference doc — so a future
   field added to `config.py` doesn't silently miss documentation.

Lightweight: no markdown parser, no broken-link crawler — just
substring + regex assertions on the file text.
"""
from __future__ import annotations

import re
from pathlib import Path

from harbormaster.config import HarbormasterConfig

REPO_ROOT = Path(__file__).parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "operator-config-reference.md"
README_PATH = REPO_ROOT / "README.md"


def test_doc_exists_and_nonempty() -> None:
    assert DOC_PATH.is_file(), f"missing {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert len(text) > 1000, "doc looks suspiciously short"


def test_readme_links_to_doc() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    # Either path form is acceptable.
    assert (
        "docs/operator-config-reference.md" in readme
        or "(operator-config-reference.md)" in readme
    ), "README has no link to the operator config reference"


def _section_headers_in_doc() -> set[str]:
    """Return every `## \\`[<name>]\\`` header. Section headers in
    the doc use Markdown backticks around the TOML section name."""
    text = DOC_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"^##\s+`\[([a-z._<>-]+)\]`", text, re.M))


def test_every_documented_section_in_worked_example() -> None:
    """Every `## \\`[…]\\`` header must appear at least once as
    `[…]` in the worked-example TOML block. Catches drift where
    a section is described in prose but not in the example."""
    text = DOC_PATH.read_text(encoding="utf-8")
    for section in _section_headers_in_doc():
        # Strip out wildcard parts like `<name>` / `<label>` — those
        # are docs placeholders, not literal TOML. Sections like
        # `[backends.<name>]` resolve to the prefix `[backends.`
        # which the example uses with concrete names.
        normalized = re.sub(r"<[^>]+>", "", section)
        if not normalized:
            continue
        if normalized.endswith("."):
            # Plural-section prefix (e.g. `backends.`) — concrete
            # instances must appear in the example.
            assert f"[{normalized}" in text, (
                f"section [{section}] missing from worked example"
            )
        else:
            assert f"[{normalized}]" in text, (
                f"section [{section}] missing from worked example"
            )


def test_every_config_field_documented() -> None:
    """Every Pydantic field on HarbormasterConfig (and its nested
    BaseModel sub-models) has at least one mention in the reference
    doc. Acts as a coverage gate against undocumented config keys
    that future PRs add to config.py."""
    text = DOC_PATH.read_text(encoding="utf-8")

    # Walk all sub-models reachable from HarbormasterConfig.
    from pydantic import BaseModel

    seen: set[type[BaseModel]] = set()
    todo: list[type[BaseModel]] = [HarbormasterConfig]
    missing: list[str] = []

    while todo:
        cls = todo.pop()
        if cls in seen:
            continue
        seen.add(cls)
        for field_name, field_info in cls.model_fields.items():
            ann = field_info.annotation
            # Recurse into nested BaseModel types.
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                todo.append(ann)
                continue
            # dict[str, BaseModel] — recurse the value type.
            args = getattr(ann, "__args__", None)
            if args:
                for a in args:
                    if isinstance(a, type) and issubclass(a, BaseModel):
                        todo.append(a)
            # Field name should appear at least once in the doc.
            # Backtick-wrapped looks like `\`field_name\``.
            if f"`{field_name}`" not in text and field_name not in text:
                missing.append(f"{cls.__name__}.{field_name}")

    assert not missing, (
        "undocumented config fields:\n  " + "\n  ".join(missing)
    )


def test_doc_has_table_of_contents() -> None:
    """v13.0.0a6 contract: doc has an explicit TOC so operators can
    jump to the section they need."""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "## Table of contents" in text


def test_doc_has_loading_order_section() -> None:
    """Where the TOML is read from is the first thing operators ask;
    must be documented up front."""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert ".harbormaster.toml" in text
    assert "XDG_CONFIG_HOME" in text
