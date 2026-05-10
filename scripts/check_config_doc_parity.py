#!/usr/bin/env python3
"""Pre-commit hook: parity check between config.py + operator-config-reference.md.

Walks every Pydantic field on `HarbormasterConfig` and its nested
sub-models. Fails (exit 1) if any field name is missing from the
operator config reference doc — same coverage rule as
`tests/unit/test_config_doc_reference.py::test_every_config_field_documented`,
extracted as a stand-alone script so the pre-commit hook can run it
without spinning up pytest.

Exits 0 on parity, 1 on undocumented fields.

Usage::

    python scripts/check_config_doc_parity.py [--doc PATH]

(v15.0.0a5 — closes v14 candidate #11.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC_PATH = REPO_ROOT / "docs" / "operator-config-reference.md"


def find_undocumented(doc_path: Path) -> list[str]:
    """Return a list of `<Model>.<field>` strings that are missing
    from the doc."""
    # Importing here so a missing dependency at install time still
    # leaves --help working.
    from pydantic import BaseModel

    from harbormaster.config import HarbormasterConfig

    text = doc_path.read_text(encoding="utf-8")

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
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                todo.append(ann)
                continue
            args = getattr(ann, "__args__", None)
            if args:
                for a in args:
                    if isinstance(a, type) and issubclass(a, BaseModel):
                        todo.append(a)
            if f"`{field_name}`" not in text and field_name not in text:
                missing.append(f"{cls.__name__}.{field_name}")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_config_doc_parity",
        description=__doc__,
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=DEFAULT_DOC_PATH,
        help=f"path to operator-config-reference.md (default: {DEFAULT_DOC_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.doc.is_file():
        sys.stderr.write(f"check_config_doc_parity: doc not found: {args.doc}\n")
        return 1

    missing = find_undocumented(args.doc)
    if missing:
        sys.stderr.write(
            "check_config_doc_parity: undocumented config fields:\n"
            + "".join(f"  - {m}\n" for m in missing)
            + f"\nFix: add the field to {args.doc} (any backtick or "
            "bare mention counts).\n",
        )
        return 1
    sys.stdout.write(
        f"check_config_doc_parity: OK ({args.doc.name})\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
