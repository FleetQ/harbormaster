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


def find_undocumented(doc_path: Path) -> list[tuple[str, str, object, object]]:
    """Return a list of ``(model_name, field_name, type_repr, default)``
    tuples for fields missing from the doc.

    v16.0.0a2: full ``FieldInfo`` extracted per offender so the
    suggested-edit emitter has type + default to render.
    """
    # Importing here so a missing dependency at install time still
    # leaves --help working.
    from pydantic import BaseModel
    from pydantic_core import PydanticUndefined

    from harbormaster.config import HarbormasterConfig

    text = doc_path.read_text(encoding="utf-8")

    seen: set[type[BaseModel]] = set()
    todo: list[type[BaseModel]] = [HarbormasterConfig]
    missing: list[tuple[str, str, object, object]] = []

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
                # Format the type annotation (drop module prefix when present).
                if hasattr(ann, "__name__"):
                    type_repr: object = ann.__name__
                else:
                    type_repr = repr(ann).replace("typing.", "")
                # Default — `PydanticUndefined` means the field is required.
                if field_info.default is not PydanticUndefined:
                    default: object = field_info.default
                elif field_info.default_factory is not None:
                    try:
                        default = field_info.default_factory()  # type: ignore[call-arg]
                    except Exception:
                        default = "<factory>"
                else:
                    default = "<required>"
                missing.append((cls.__name__, field_name, type_repr, default))
    return missing


def render_suggested_edit(
    missing: list[tuple[str, str, object, object]],
) -> str:
    """v16.0.0a2: emit a copy-paste markdown block listing each
    undocumented field with its model, type, and default. Operators
    paste the block verbatim into ``operator-config-reference.md``
    under the right ``[section]`` heading.
    """
    if not missing:
        return ""
    lines: list[str] = [
        "",
        "# --- copy-paste into docs/operator-config-reference.md ---",
        "",
    ]
    # Group by model so the operator can put each block under the
    # right `[section]` heading.
    by_model: dict[str, list[tuple[str, object, object]]] = {}
    for model_name, field_name, type_repr, default in missing:
        by_model.setdefault(model_name, []).append(
            (field_name, type_repr, default),
        )
    for model_name in sorted(by_model.keys()):
        lines.append(f"### {model_name}")
        lines.append("")
        for field_name, type_repr, default in by_model[model_name]:
            default_repr = repr(default) if not isinstance(default, str) else default
            lines.append(
                f"- `{field_name}` (`{type_repr}`, default `{default_repr}`) — "
                "DESCRIBE behaviour and operator impact here.",
            )
        lines.append("")
    lines.append("# --- end paste block ---")
    return "\n".join(lines) + "\n"


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
            + "".join(
                f"  - {model}.{field}\n" for model, field, _t, _d in missing
            )
            + f"\nFix: add the field to {args.doc} (any backtick or "
            "bare mention counts).\n",
        )
        # v16.0.0a2: emit a copy-paste-ready markdown stanza on stderr
        # so the operator doesn't have to look up types + defaults by
        # hand. The block is delimited by `# ---` markers so it's
        # trivially greppable in CI logs.
        sys.stderr.write(render_suggested_edit(missing))
        return 1
    sys.stdout.write(
        f"check_config_doc_parity: OK ({args.doc.name})\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
