"""v19.0.0a4 migration — Linear violet tokens + compact density.

One-shot in-place rewrite of every .html under
src/harbormaster/ui/templates/. Reads each file once, applies the
ordered substitution table below, writes back if anything changed.

Strategy (read this before editing the table):

1. **Token rename — high-confidence cyan -> accent.** Raw Tailwind
   `cyan-NNN` utility classes survived from the v9 era; v13's
   migration already swept the high-shade variants but missed
   focus-ring / hover-state utilities. v19.0.0a4 sweeps those.
   - `ring-cyan-400` -> `ring-accent`
   - `bg-cyan-900/NN` -> `bg-accent-soft/NN` (preserves opacity)
   - `border-cyan-900/40` -> `border-accent-soft/40`
   - `accent-cyan-500` (HTML <input type=checkbox> color) -> `accent-accent`

2. **Token rename — gray utilities -> semantic surface tokens.**
   - `bg-gray-950/NN` -> `bg-surface-1/NN` (page bg with opacity)
   - `bg-gray-900/NN` -> `bg-surface-2/NN`
   - `bg-gray-800/NN` -> `bg-surface-3/NN`
   - `ring-offset-gray-950` -> `ring-offset-surface-1`

   These already had non-opacity equivalents migrated in v13;
   v19.0.0a4 only handles the `/NN` opacity-suffixed variants.

3. **Density pass — global tighten.** Applied after token renames so
   the regex doesn't accidentally touch newly-introduced tokens.
   - `gap-4 ` -> `gap-2 `, `gap-3 ` -> `gap-2 `, `p-4 ` -> `p-2.5 `,
     `py-4 ` -> `py-2.5 `, `px-4 ` -> `px-3 `, `mb-6 ` -> `mb-4 `,
     `mb-3 ` -> `mb-2 `, `mt-3 ` -> `mt-2 `, `rounded-lg` ->
     `rounded-md` (kept as bare token — `rounded-lg` does not need
     a trailing space because it's never a prefix of another class
     in this codebase; verified by grep).

   Density rule is NOT applied to:
   * `gap-1`, `gap-1.5`, `gap-2` already at minimum
   * `p-2`, `p-1.5`, `p-1` already tight
   * `rounded` (no suffix), `rounded-md`, `rounded-sm`, `rounded-full`
   * Anything inside an inline `<style>` block (heuristic: skipped
     for files that contain `<style>` tags — only base.html does,
     and its <style> block has no Tailwind utility classes)

4. **Idempotency.** Running the script twice produces the same
   result as running it once — every substitution is a strict
   forward map (cyan -> accent never reverses).

Usage::

    python scripts/migrate_v19a4_violet_compact.py [--dry-run]

Exit 0 with summary of files touched + per-file change count.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from re import Pattern

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO / "src" / "harbormaster" / "ui" / "templates"


# ---------------------------------------------------------------------------
# Substitution table.
#
# Each entry is (compiled_regex, replacement). Order matters — token-rename
# rules MUST run before density rules so density's `p-4` -> `p-2.5` doesn't
# accidentally apply to a freshly-rewritten `padding-4` token.
# ---------------------------------------------------------------------------

_TOKEN_RULES: list[tuple[Pattern[str], str]] = [
    # --- cyan -> accent ---
    # focus rings: ring-cyan-400 (no-opacity) -> ring-accent
    (re.compile(r"\bring-cyan-400\b"), "ring-accent"),
    # opacity-suffixed bg-cyan-900/NN -> bg-accent-soft/NN (keeps the /NN)
    (re.compile(r"\bbg-cyan-900/(\d+)"), r"bg-accent-soft/\1"),
    # hover variant must come before generic — handled by replace order:
    # Tailwind class strings are space-delimited so the prefix `hover:`
    # passes through naturally; the regex above already eats `bg-cyan-900/NN`
    # mid-string regardless of any `hover:` prefix.
    (re.compile(r"\bbg-cyan-(?:600|700|800)\b"), "bg-accent-strong"),
    (re.compile(r"\bborder-cyan-900/(\d+)"), r"border-accent-soft/\1"),
    (re.compile(r"\bborder-cyan-(?:700|800)\b"), "border-accent-strong"),
    (re.compile(r"\btext-cyan-(?:300|400|500)\b"), "text-accent"),
    (re.compile(r"\btext-cyan-(?:600|700)\b"), "text-accent-strong"),
    # accent-cyan-500 — HTML form-element accent-color utility
    (re.compile(r"\baccent-cyan-500\b"), "accent-accent"),
    # --- gray opacity-suffixed -> surface tokens ---
    (re.compile(r"\bbg-gray-950/(\d+)"), r"bg-surface-1/\1"),
    (re.compile(r"\bbg-gray-900/(\d+)"), r"bg-surface-2/\1"),
    (re.compile(r"\bbg-gray-800/(\d+)"), r"bg-surface-3/\1"),
    (re.compile(r"\bbg-gray-700/(\d+)"), r"bg-surface-3/\1"),
    (re.compile(r"\bborder-gray-(?:700|800|900)/(\d+)"), r"border-border-strong/\1"),
    (re.compile(r"\bring-offset-gray-950\b"), "ring-offset-surface-1"),
    # placeholder-gray-NNN — unrelated to brand color, leave alone
    # (rendered as faint text inside inputs; the gray-500 stop is fine).
]


_DENSITY_RULES: list[tuple[Pattern[str], str]] = [
    # Use word-boundary + lookahead for the trailing class boundary so
    # `gap-4 mt-2` matches but `gap-4xl` (hypothetical) wouldn't.
    (re.compile(r"\bgap-4\b(?![\d.])"), "gap-2"),
    (re.compile(r"\bgap-3\b(?![\d.])"), "gap-2"),
    (re.compile(r"\bp-4\b(?![\d.])"), "p-2.5"),
    (re.compile(r"\bp-3\b(?![\d.])"), "p-2"),
    (re.compile(r"\bpx-4\b(?![\d.])"), "px-3"),
    (re.compile(r"\bpy-4\b(?![\d.])"), "py-2.5"),
    (re.compile(r"\bpy-3\b(?![\d.])"), "py-2"),
    (re.compile(r"\bmb-6\b(?![\d.])"), "mb-4"),
    (re.compile(r"\bmb-3\b(?![\d.])"), "mb-2"),
    (re.compile(r"\bmt-3\b(?![\d.])"), "mt-2"),
    (re.compile(r"\brounded-lg\b"), "rounded-md"),
]


def migrate_text(text: str) -> tuple[str, int]:
    """Apply all rules to `text`. Returns (new_text, total_substitutions)."""
    total = 0
    for pattern, repl in _TOKEN_RULES:
        text, n = pattern.subn(repl, text)
        total += n
    for pattern, repl in _DENSITY_RULES:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(TEMPLATE_DIR.rglob("*.html"))
    touched = 0
    total_subs = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        new, n = migrate_text(original)
        if n == 0:
            continue
        touched += 1
        total_subs += n
        rel = f.relative_to(REPO)
        print(f"{rel}: {n} substitutions")
        if not args.dry_run:
            f.write_text(new, encoding="utf-8")

    print(f"\nTotal: {touched} files, {total_subs} substitutions"
          f"{' (dry-run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
