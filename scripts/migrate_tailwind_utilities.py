"""v13.0.0a2: Tailwind v4 utility-class migration.

Closes the v9.0.0a1 deferral. Walks every Jinja template under
`src/harbormaster/ui/templates/` and rewrites raw Tailwind color
utilities (e.g. `bg-cyan-700`, `text-gray-400`) to the semantic
tokens defined in `tailwind.input.css`'s `@theme` block.

Strategy:

- Whole-token replacement only (regex word-boundary). We don't try
  to handle every possible variant — high-confidence mappings only.
  Anything ambiguous is left alone for human review.
- Idempotent. Running twice is a no-op.
- Reports the count per template so the v13.0.0a2 retro can quote
  numbers without re-grepping.

The v13.0.0a1 screenshot-diff harness is what makes this safe to
ship: bootstrap baselines on the v12 tip, run the script, run the
harness, ship if green.

Usage:
    .venv/bin/python scripts/migrate_tailwind_utilities.py
    .venv/bin/python scripts/migrate_tailwind_utilities.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "src" / "harbormaster" / "ui" / "templates"


# Map raw utility → semantic token. Order matters only for reporting;
# regex is word-boundary safe so order doesn't affect correctness.
#
# Mapping rationale (matches tailwind.input.css):
#   --color-foreground         = primary text on dark   (was text-gray-100/200)
#   --color-foreground-muted   = secondary              (was text-gray-300/400)
#   --color-foreground-subtle  = tertiary               (was text-gray-500/600)
#   --color-surface-1/2/3      = canvas → elevated      (was bg-gray-950/900/800)
#   --color-accent/strong/soft = cyan family            (was text/bg-cyan-*)
#   --color-success            = green                  (was text/bg-emerald-*)
#   --color-warning            = amber                  (was text/bg-amber-*)
#   --color-danger             = red                    (was text/bg-rose-* / text-red-*)
#   --color-info               = purple/cyan            (was text-purple-300)
#   --color-border / -strong   = border                 (was border-gray-700/800)
MAPPINGS: dict[str, str] = {
    # foreground (text)
    "text-gray-100": "text-foreground",
    "text-gray-200": "text-foreground",
    "text-gray-300": "text-foreground-muted",
    "text-gray-400": "text-foreground-muted",
    "text-gray-500": "text-foreground-subtle",
    "text-gray-600": "text-foreground-subtle",
    "text-gray-700": "text-foreground-subtle",
    # accent (cyan)
    "text-cyan-100": "text-accent",
    "text-cyan-200": "text-accent",
    "text-cyan-300": "text-accent",
    "text-cyan-400": "text-accent",
    "text-cyan-500": "text-accent-strong",
    "text-cyan-600": "text-accent-strong",
    "text-cyan-700": "text-accent-strong",
    # state — text
    "text-emerald-300": "text-success",
    "text-emerald-400": "text-success",
    "text-amber-300": "text-warning",
    "text-amber-400": "text-warning",
    "text-rose-300": "text-danger",
    "text-rose-400": "text-danger",
    "text-red-300": "text-danger",
    "text-red-400": "text-danger",
    "text-purple-300": "text-info",
    "text-purple-400": "text-info",
    # surfaces (bg)
    "bg-gray-950": "bg-surface-1",
    "bg-gray-900": "bg-surface-2",
    "bg-gray-800": "bg-surface-3",
    # accent backgrounds (no opacity variants — those stay raw for now)
    "bg-cyan-600": "bg-accent",
    "bg-cyan-700": "bg-accent-strong",
    "bg-cyan-800": "bg-accent-strong",
    # borders
    "border-gray-700": "border-border",
    "border-gray-800": "border-border",
    "border-gray-900": "border-border-strong",
    "border-cyan-700": "border-accent-strong",
    "border-cyan-800": "border-accent-strong",
    "border-amber-700": "border-warning",
}


def migrate_text(text: str) -> tuple[str, dict[str, int]]:
    """Apply MAPPINGS to `text`. Returns (new_text, per-mapping count)."""
    counts: dict[str, int] = {}
    for src, dst in MAPPINGS.items():
        # Word-boundary so `bg-gray-950/40` (with opacity) is NOT matched
        # by the `bg-gray-950` rule (the trailing `/` isn't a word char so
        # `\b` would actually match — guard against that with a negative
        # lookahead for `/`).
        pattern = re.compile(rf"(?<![\w-]){re.escape(src)}(?![\w/-])")
        new_text, n = pattern.subn(dst, text)
        if n:
            counts[src] = n
            text = new_text
    return text, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes but don't write files")
    args = parser.parse_args()

    total: dict[str, int] = {}
    files_touched = 0

    for path in sorted(TEMPLATES.rglob("*.html")):
        original = path.read_text(encoding="utf-8")
        new, counts = migrate_text(original)
        if not counts:
            continue
        files_touched += 1
        rel = path.relative_to(REPO_ROOT)
        print(f"{rel}: {sum(counts.values())} replacements")
        for src, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>4}  {src} → {MAPPINGS[src]}")
            total[src] = total.get(src, 0) + n
        if not args.dry_run:
            path.write_text(new, encoding="utf-8")

    print(f"\nTotal: {sum(total.values())} replacements across {files_touched} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
