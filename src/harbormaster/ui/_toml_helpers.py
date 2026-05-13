"""Shared TOML serializer for UI-side config writers (v24.0.0a4).

Hand-written serializer extracted from routes.py during the v23/v24
routes split. Used by both:

- ``routes_budgets.py`` (``_write_project_budget_toml``) — writes
  ``[budget] daily_call_budget`` into ``<project>/.harbormaster.toml``
- ``routes.py`` accent picker (``_write_accent_toml``) — writes
  ``[ui] accent_hue/accent_chroma`` into the user config.toml

There is no stdlib TOML writer in Python 3.11+, and adding ``tomli-w``
for a few two-line tables is over-spec. This module covers the cases
we actually use: bool / int / float / str / list of scalars. Nested
tables and inline tables are out of scope (schema-policed elsewhere).
"""
from __future__ import annotations


def toml_value(v: object) -> str:
    """Render a Python value as a TOML scalar / array literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        # Basic-string with escaping for the cases we expect.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return f'"{v!s}"'
