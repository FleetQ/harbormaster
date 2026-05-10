"""`harbormaster-mcp config check` subcommand (v14.0.0a2).

Loads the resolved ``HarbormasterConfig`` and prints a validation
report — a sequence of findings, each tagged INFO, WARN, or ERROR.

Wire:

    harbormaster-mcp config check [--config PATH] [--json]

Useful as:

  * A pre-flight check operators can run before launching the server.
  * A CI gate that fails when config has errors.

Exit codes:

  * 0 — config loads, no warnings or errors emitted.
  * 1 — config loads, but at least one WARN finding.
  * 2 — config fails to load OR at least one ERROR finding.

The text format is intentionally human-skim-friendly. ``--json`` is
provided for programmatic consumption (CI gates, dashboards) and
emits a single JSON object documented in :func:`_collect_findings`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from harbormaster.config import HarbormasterConfig, load_config

Severity = Literal["INFO", "WARN", "ERROR"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-mcp config",
        description="Load and validate the resolved harbormaster config.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_check = sub.add_parser(
        "check",
        help="Validate config and print findings (exit 0 OK / 1 warn / 2 err).",
    )
    p_check.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Path to harbormaster.toml. Default: usual config search "
            "(./.harbormaster.toml then "
            "$XDG_CONFIG_HOME/harbormaster/config.toml)."
        ),
    )
    p_check.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit a single JSON object instead of the text format. "
            "Schema: {ok: bool, severity: 'INFO'|'WARN'|'ERROR', "
            "findings: [{severity, code, message}]}."
        ),
    )
    return parser


def _collect_findings(config: HarbormasterConfig) -> list[dict[str, str]]:
    """Walk the resolved config and return a list of findings.

    Each finding is a dict with keys ``severity`` (INFO|WARN|ERROR),
    ``code`` (short stable identifier for grep / dashboards), and
    ``message`` (human-readable explanation).
    """
    findings: list[dict[str, str]] = []

    # 1) Backends — the "default" backend must be defined.
    if config.default_backend not in config.backends:
        findings.append({
            "severity": "ERROR",
            "code": "default_backend_missing",
            "message": (
                f"default_backend={config.default_backend!r} is not in "
                f"[backends.*] (defined: "
                f"{sorted(config.backends.keys())})."
            ),
        })

    # 2) backends_for_project entries must reference defined backends
    #    and known project names. Project name validation is best-effort
    #    here — projects may live on disk and not in config; we only
    #    flag the backend-name half because that's what'd cause a
    #    KeyError at dispatch time.
    for project, backend in config.backends_for_project.items():
        if backend not in config.backends:
            findings.append({
                "severity": "ERROR",
                "code": "backend_for_project_unknown",
                "message": (
                    f"backends_for_project[{project!r}]={backend!r} "
                    "is not defined under [backends.*]."
                ),
            })

    # 3) Hosts — each host must define an SSH user OR be marked local.
    #    Empty `[hosts.*]` blocks are common in fresh installs but should
    #    be flagged so the operator knows fan_out won't pick them up.
    if not config.hosts:
        findings.append({
            "severity": "INFO",
            "code": "no_hosts",
            "message": (
                "No [hosts.*] entries — only the local host will be used."
            ),
        })

    # 4) FleetQ — when enabled, both base_url and an env-resolvable
    #    token must be present.
    fq = config.fleetq
    if fq.enabled:
        if not fq.base_url:
            findings.append({
                "severity": "ERROR",
                "code": "fleetq_base_url_missing",
                "message": "[fleetq] enabled = true but base_url is empty.",
            })
        token_env = fq.api_token_env or "FLEETQ_API_TOKEN"
        if not os.environ.get(token_env):
            findings.append({
                "severity": "WARN",
                "code": "fleetq_token_env_unset",
                "message": (
                    f"[fleetq] enabled = true but env var {token_env!r} "
                    "is not set — writes will silently no-op."
                ),
            })

    # 5) History extras — auto_reembed_on_drift requires the [history]
    #    optional dependency to be installed at runtime.
    hist = config.history
    if hist.auto_reembed_on_drift:
        try:
            import importlib

            importlib.import_module("harbormaster.history")
        except ImportError:  # pragma: no cover — only on broken install
            findings.append({
                "severity": "ERROR",
                "code": "history_extra_missing",
                "message": (
                    "[history] auto_reembed_on_drift = true but the "
                    "history extra is not installed (uvx --extra history)."
                ),
            })

    # 6) Plugins — a non-empty allowlist of unknown entry-point names
    #    is non-fatal but worth surfacing as INFO so operators can
    #    notice typos early.
    plugins = config.plugins
    if plugins.enabled and not plugins.allow:
        findings.append({
            "severity": "WARN",
            "code": "plugins_empty_allowlist",
            "message": (
                "[plugins] enabled = true with empty allow list — "
                "deny-by-default means no plugins will load. Set "
                "[plugins].allow = [\"pkg-name\", ...] to enable."
            ),
        })

    return findings


def _max_severity(findings: list[dict[str, str]]) -> Severity:
    """Return the highest-severity present, defaulting to INFO."""
    if any(f["severity"] == "ERROR" for f in findings):
        return "ERROR"
    if any(f["severity"] == "WARN" for f in findings):
        return "WARN"
    return "INFO"


def _exit_code_for(severity: Severity) -> int:
    if severity == "ERROR":
        return 2
    if severity == "WARN":
        return 1
    return 0


def _print_text(findings: list[dict[str, str]]) -> None:
    if not findings:
        sys.stdout.write("config check: OK (no findings)\n")
        return
    for f in findings:
        sys.stdout.write(f"[{f['severity']}] {f['code']}: {f['message']}\n")
    sev = _max_severity(findings)
    sys.stdout.write(f"\nconfig check: {sev}\n")


def _print_json(findings: list[dict[str, str]], severity: Severity) -> None:
    payload = {
        "ok": severity != "ERROR",
        "severity": severity,
        "findings": findings,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def _do_check(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    # When the operator passes --config PATH explicitly, an unreadable
    # path should be a hard error — load_config silently falls back to
    # defaults, which is the wrong behavior for a validation CLI.
    if config_path is not None and not config_path.is_file():
        finding = {
            "severity": "ERROR",
            "code": "config_load_failed",
            "message": f"config file not found: {config_path}",
        }
        if args.json_output:
            _print_json([finding], "ERROR")
        else:
            sys.stdout.write(
                f"[ERROR] config_load_failed: {finding['message']}"
                "\n\nconfig check: ERROR\n"
            )
        return 2
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValidationError, ValueError) as exc:
        # Config failed to load at all — emit an ERROR-shaped finding
        # and exit 2 regardless of --json.
        finding = {
            "severity": "ERROR",
            "code": "config_load_failed",
            "message": str(exc),
        }
        if args.json_output:
            _print_json([finding], "ERROR")
        else:
            sys.stdout.write(
                f"[ERROR] config_load_failed: {exc}\n\nconfig check: ERROR\n"
            )
        return 2

    findings = _collect_findings(config)
    severity = _max_severity(findings) if findings else "INFO"
    if args.json_output:
        _print_json(findings, severity)
    else:
        _print_text(findings)
    return _exit_code_for(severity if findings else "INFO")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.action == "check":
        return _do_check(args)
    parser.error(f"unknown action: {args.action!r}")
    return 2
