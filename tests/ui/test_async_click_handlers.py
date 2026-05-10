"""v11.0.0a7: x-data unhandled-promise lint.

Sister-pattern to v7.0.0a2's measure-dependent template audit. An
Alpine `@click="method()"` binding that calls an `async` factory
method silently swallows any exception thrown inside the promise
unless the method body has its own try/catch (or the call site
adds `.catch(...)`). Errors swallowed in the browser produce
ghost UIs — the user clicks, nothing happens, no console message.

This audit walks every template, identifies Alpine handler
bindings (`@click`, `@submit`, `@change`, `@input`), extracts the
factory method name, then parses the corresponding factory in the
script tag(s) below to confirm:

  - Either the method is NOT `async` (regular function, exceptions
    propagate normally to Alpine's error handler), OR
  - The async method body contains a `try {` AND a `catch (` token,
    OR
  - The handler binding has an inline `.catch(`.

The audit is heuristic — it parses templates as text, not via a
real JS AST — but the failure mode it catches is structural enough
that string scanning is sufficient. False-positive cases can be
allowlisted with a code-comment justification.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src" / "harbormaster" / "ui" / "templates"
)

# Allowlisted (template, factory_method) pairs. Each must justify
# WHY the missing try/catch isn't a ghost-UI risk.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    # Add justified exceptions here as (relative_path, method_name).
})

_HANDLER_RE = re.compile(
    r'@(?:click|submit|change|input|keydown|keyup)(?:\.[a-z0-9]+)*\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)
# Match a method invocation like `methodName()` or
# `methodName(arg1, arg2)`. We only care about the IDENTIFIER, not the args.
# Allow leading `$` so we can detect (and skip) Alpine magics like
# $dispatch / $nextTick instead of stripping the dollar and matching the
# rest as a real method.
_METHOD_CALL_RE = re.compile(r"(\$?[a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def _all_templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.glob("**/*.html"))


def _extract_handler_method_calls(template_text: str) -> set[str]:
    """For each Alpine handler binding, return the set of called
    method identifiers (just the names, not the args)."""
    out: set[str] = set()
    for match in _HANDLER_RE.finditer(template_text):
        expr = match.group(1)
        # Skip $dispatch, console.log, alert, etc — we only check
        # identifiers that look like factory methods.
        for m in _METHOD_CALL_RE.finditer(expr):
            ident = m.group(1)
            if ident in {
                "$dispatch", "$nextTick", "$watch", "$store",
                "console", "alert", "confirm", "preventDefault",
                "stopPropagation", "Number", "String", "Boolean",
                "JSON", "encodeURIComponent", "decodeURIComponent",
                "Math", "Date", "Object", "Array",
            }:
                continue
            out.add(ident)
    return out


def _extract_async_methods(template_text: str) -> set[str]:
    """Find method names declared as `async <name>(` inside the
    factory function bodies in <script> tags."""
    out: set[str] = set()
    # Match `async methodName(` — note Alpine factories use the
    # shorthand object-method syntax inside the returned object,
    # so the method declaration is `<name>(...)` or `async <name>(...)`.
    for m in re.finditer(
        r"\basync\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", template_text,
    ):
        out.add(m.group(1))
    return out


def _method_has_try_catch(template_text: str, method_name: str) -> bool:
    """Heuristic: locate `async <method_name>(` and check whether
    the next 4000 characters of the template (covering the method
    body) contain BOTH `try {` and `catch (`."""
    pattern = re.compile(
        r"\basync\s+" + re.escape(method_name) + r"\s*\(",
    )
    m = pattern.search(template_text)
    if not m:
        return False
    body_window = template_text[m.end():m.end() + 4000]
    return ("try" in body_window) and ("catch" in body_window)


def _binding_has_inline_catch(template_text: str, method_name: str) -> bool:
    """Check whether ANY handler binding for this method calls it
    with `.catch(...)` chained on (e.g. `@click="foo().catch(...)"`)."""
    pattern = re.compile(
        r'@\w+(?:\.[a-z0-9]+)*\s*=\s*"[^"]*\b'
        + re.escape(method_name)
        + r'\s*\([^"]*\.catch\s*\(',
    )
    return bool(pattern.search(template_text))


def _scan_template(path: Path) -> list[tuple[str, str]]:
    """Return list of (method_name, reason) for unhandled async-handler
    violations in the template at `path`."""
    text = path.read_text(encoding="utf-8")
    handler_methods = _extract_handler_method_calls(text)
    async_methods = _extract_async_methods(text)

    violations: list[tuple[str, str]] = []
    for method in sorted(handler_methods & async_methods):
        if (path.name, method) in ALLOWLIST:
            continue
        if _method_has_try_catch(text, method):
            continue
        if _binding_has_inline_catch(text, method):
            continue
        violations.append((
            method,
            f"async method `{method}` is bound to a handler "
            f"in {path.name} but has no try/catch and no inline "
            f".catch — promise rejections will be silently swallowed",
        ))
    return violations


def test_no_unhandled_async_click_handlers() -> None:
    """Walk every template; fail with the consolidated violation
    list when any binding falls outside the allowlist."""
    failures: dict[str, list[tuple[str, str]]] = {}
    for path in _all_templates():
        v = _scan_template(path)
        if v:
            failures[str(path.relative_to(TEMPLATE_DIR))] = v

    if failures:
        msg_lines = ["unhandled async-handler bindings detected:"]
        for tpl, items in failures.items():
            msg_lines.append(f"  {tpl}:")
            for _, reason in items:
                msg_lines.append(f"    - {reason}")
        msg_lines.append(
            "Fix: wrap the body in try/catch, OR add `.catch(...)` "
            "to the handler binding, OR allowlist the pair in "
            "tests/ui/test_async_click_handlers.py with a comment.",
        )
        pytest.fail("\n".join(msg_lines))


# -- regression / smoke -------------------------------------------------


def test_handler_extractor_finds_alpine_clicks() -> None:
    sample = '<button @click="foo()">x</button>'
    assert _extract_handler_method_calls(sample) == {"foo"}


def test_handler_extractor_skips_alpine_directives() -> None:
    sample = '<button @click="$dispatch(\'x\')">x</button>'
    assert _extract_handler_method_calls(sample) == set()


def test_async_method_extractor_finds_decls() -> None:
    sample = "async loadStuff() { return 1 }"
    assert _extract_async_methods(sample) == {"loadStuff"}


def test_method_has_try_catch_detects() -> None:
    sample = "async loadStuff() { try { return 1 } catch (e) {} }"
    assert _method_has_try_catch(sample, "loadStuff") is True


def test_method_has_try_catch_negative() -> None:
    sample = "async loadStuff() { return 1 }"
    assert _method_has_try_catch(sample, "loadStuff") is False


def test_binding_has_inline_catch_detects() -> None:
    sample = '<button @click="foo().catch(e => 0)">x</button>'
    assert _binding_has_inline_catch(sample, "foo") is True
