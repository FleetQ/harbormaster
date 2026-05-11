"""Regression test for v20.0.0a1 — guard against the Jinja-tojson-inside-
double-quoted-x-data anti-pattern that bit v19.0.0a8 (memoriesEditor) and
v20.0.0a1 (trajectoryList).

The bug: Jinja's ``tojson`` filter HTML-escapes via ``&quot;`` in attribute
context. When the host attribute is double-quoted, the escaped quotes
collide with the surrounding attribute and Alpine fails to parse the
expression. The fix is to single-quote the outer attribute (so embedded
double quotes survive untouched) **or** to pass primitive strings via
``'{{ var | e }}'`` form.

This test scans every Jinja template under
``src/harbormaster/ui/templates/`` and asserts that no ``x-data`` attribute
of the shape ``x-data="factory({{ ... }})"`` exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)

# Match an x-data attribute that:
#   - opens with a DOUBLE quote
#   - calls a JS factory (alphanumeric identifier + "(" )
#   - contains a Jinja expression that emits raw JSON / unescaped output
#     (``tojson``, ``safe``, or no escaping filter) — these inject literal
#     double quotes that collide with the surrounding attribute.
#
# The SAFE pattern ``x-data="factory('{{ var | e }}')"`` is allowed:
#   - the inner JS string is single-quoted
#   - ``| e`` escapes ``<>&"`` to entities, so no raw ``"`` ever lands
#     in the attribute value.
_DOUBLE_QUOTED_XDATA_WITH_JINJA = re.compile(
    r'x-data="([A-Za-z_][A-Za-z0-9_]*\([^"]*?\{\{[^}]*?\}\}[^"]*?)"',
    re.DOTALL,
)

# A Jinja expression is SAFE inside a double-quoted attribute only when it
# is HTML-escaped (``| e`` or ``| escape``). ``tojson`` and ``safe`` emit
# raw double quotes and are anti-patterns here.
_SAFE_FILTER = re.compile(r"\|\s*(?:e|escape)\b")
_UNSAFE_FILTER = re.compile(r"\|\s*(?:tojson|safe)\b")


def _iter_templates() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


@pytest.mark.parametrize("template", _iter_templates(), ids=lambda p: p.name)
def test_no_jinja_inside_double_quoted_xdata(template: Path) -> None:
    text = template.read_text(encoding="utf-8")
    offenders: list[str] = []
    for match in _DOUBLE_QUOTED_XDATA_WITH_JINJA.finditer(text):
        body = match.group(1)
        # Reject if it uses tojson/safe (always unsafe in dq attribute) OR
        # uses no escape filter at all (raw output may contain quotes).
        if _UNSAFE_FILTER.search(body) or not _SAFE_FILTER.search(body):
            offenders.append(match.group(0))
    assert not offenders, (
        f"{template.relative_to(TEMPLATES_DIR.parents[3])} contains "
        f"x-data=\"factory({{...}})\" with unsafe Jinja interpolation. "
        f"Switch the outer attribute to single quotes "
        f"(x-data='factory(...)') so embedded double quotes from "
        f"tojson/safe survive, OR pass primitive strings via "
        f"'{{{{ var | e }}}}'. Offending matches: {offenders}"
    )


def test_audit_finds_at_least_one_template() -> None:
    """Sanity: the regex audit must actually be scanning templates."""
    templates = _iter_templates()
    assert len(templates) > 10, (
        f"Expected to scan many templates, only found {len(templates)}. "
        f"Did the templates dir move?"
    )
