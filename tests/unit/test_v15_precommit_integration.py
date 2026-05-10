"""v15.0.0a5 — pre-commit hook integration."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARITY_SCRIPT = REPO_ROOT / "scripts" / "check_config_doc_parity.py"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
EXAMPLE_TOML = REPO_ROOT / "examples" / "harbormaster.toml"


# -- pre-commit config + example file presence -------------------


def test_precommit_config_exists_at_repo_root() -> None:
    assert PRECOMMIT_CONFIG.is_file()


def test_precommit_config_declares_both_hooks() -> None:
    text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    assert "harbormaster-config-check" in text
    assert "harbormaster-config-doc-parity" in text


def test_precommit_config_runs_config_check_against_example() -> None:
    text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    assert "harbormaster-mcp config check --config examples/harbormaster.toml" in text


def test_precommit_does_not_touch_github_workflows() -> None:
    """SAFETY rail (v15 binding lesson #5): pre-commit MUST live at
    repo root + scripts/, never in .github/workflows/.

    Strips YAML comments first — a comment that REFERENCES the path
    (e.g. "deliberately DO NOT touch .github/workflows") is allowed,
    but no hook config or `entry:` line may reference it."""
    text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    non_comment_lines = [
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    ]
    assert ".github/workflows" not in "\n".join(non_comment_lines)


def test_example_toml_exists_and_loads_cleanly() -> None:
    """The example used by the pre-commit hook must be a valid
    HarbormasterConfig — otherwise the hook fails on a clean checkout."""
    assert EXAMPLE_TOML.is_file()
    from harbormaster.config import load_config

    cfg = load_config(EXAMPLE_TOML)
    # Smoke: the example exercises every section we ship.
    assert cfg.projects.glob == ["~/htdocs/*"]
    assert cfg.plugins.enabled is False
    # v15.0.0a4 budget section is present and parses.
    assert cfg.budget.daily_call_budget_per_tool == {}


# -- doc-parity script behaviour --------------------------------


def test_parity_script_exists_and_executable() -> None:
    assert PARITY_SCRIPT.is_file()
    text = PARITY_SCRIPT.read_text(encoding="utf-8")
    # Stand-alone shebang so pre-commit can call it.
    assert text.startswith("#!/usr/bin/env python3")


def test_parity_script_passes_against_current_doc() -> None:
    """The shipped state must pass; otherwise pre-commit blocks every
    commit on a clean checkout."""
    proc = subprocess.run(
        [sys.executable, str(PARITY_SCRIPT)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, (
        f"parity script failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_parity_script_fails_on_undocumented_field(
    tmp_path: Path,
) -> None:
    """When a config field is missing from the doc, the script must
    exit 1 with a clear message naming the field."""
    # Build a doc that's missing the v15.0.0a4 budget field.
    truncated = tmp_path / "doc.md"
    truncated.write_text(
        "# Operator config reference\n\n## `[server]`\n\nui_port etc.\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(PARITY_SCRIPT), "--doc", str(truncated)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 1
    # Names the offender in stderr.
    assert "daily_call_budget_per_tool" in proc.stderr


def test_parity_script_returns_1_when_doc_missing(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable, str(PARITY_SCRIPT),
            "--doc", str(tmp_path / "no-such-doc.md"),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 1
    assert "doc not found" in proc.stderr


# -- end-to-end: config check CLI passes against example -------


def test_config_check_cli_passes_against_example() -> None:
    """Replicate what the pre-commit hook does — invoke the CLI.

    Inject the worktree's ``src/`` to PYTHONPATH so the test sees the
    same harbormaster module the editor sees, not the venv-installed
    snapshot (the venv may be a few commits behind a fresh worktree).
    """
    import os

    env = os.environ.copy()
    src_dir = REPO_ROOT / "src"
    env["PYTHONPATH"] = (
        f"{src_dir}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    )
    # Always invoke via the module entry point so the venv's actual
    # `harbormaster-mcp` script doesn't have to be on $PATH (it
    # often isn't under pytest). Behaviour is identical — the
    # script is a thin shim over `harbormaster.__main__:main`.
    argv = [
        sys.executable, "-m", "harbormaster",
        "config", "check", "--config", str(EXAMPLE_TOML),
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )
    # config check exits 0 on OK, 1 on warning, 2 on error.
    # We accept 0 or 1 — the example may surface "no projects found"
    # (warning) on a CI box without ~/htdocs/* but should never error.
    assert proc.returncode in (0, 1), (
        f"config check failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


# -- README documentation -------------------------------------


def test_readme_documents_precommit_setup() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # README must teach operators how to install + opt in.
    assert "pre-commit" in readme.lower()
    assert "pre-commit install" in readme


# Tiny guard so pytest knows pytest is required (silences IDE warnings).
def test_pytest_imported() -> None:
    assert pytest.__version__
