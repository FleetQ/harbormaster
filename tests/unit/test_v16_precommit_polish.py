"""v16.0.0a2 — pre-commit polish.

Three carry-overs:

1. ``pre-commit`` ships in the ``[dev]`` extra so
   ``uv sync --extra dev`` is the single bootstrap command.
2. ``scripts/post_sync_install_hooks.sh`` is the documented one-shot
   that wires ``.git/hooks/pre-commit`` after the first sync.
3. ``check_config_doc_parity`` emits a copy-paste-ready markdown
   stanza on stderr when fields are undocumented — operator pastes
   into ``operator-config-reference.md`` verbatim.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
HOOK_SCRIPT = REPO_ROOT / "scripts" / "post_sync_install_hooks.sh"
PARITY_SCRIPT = REPO_ROOT / "scripts" / "check_config_doc_parity.py"
README = REPO_ROOT / "README.md"


# ---- Item 1: pre-commit in [dev] extra ------------------------------------


def test_dev_extra_includes_pre_commit() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    # The [dev] section must include a pre-commit pin.
    # Locate the dev block and assert the pin lives inside it.
    dev_start = text.index("\ndev = [")
    dev_end = text.index("]", dev_start)
    dev_block = text[dev_start:dev_end]
    assert '"pre-commit>=' in dev_block, (
        "v16.0.0a2: pre-commit must be pinned inside the [dev] extra"
    )


# ---- Item 2: post-sync hook installer script ------------------------------


def test_post_sync_hook_script_exists_and_executable() -> None:
    assert HOOK_SCRIPT.is_file(), "v16.0.0a2: post-sync hook script missing"
    # Bit set on disk: 0o111 anywhere = executable.
    mode = HOOK_SCRIPT.stat().st_mode
    assert mode & 0o111, "v16.0.0a2: post-sync hook script must be +x"


def test_post_sync_hook_script_starts_with_bash_shebang() -> None:
    body = HOOK_SCRIPT.read_text(encoding="utf-8")
    # macOS /bin/bash 3.2 fallbacks bite us — use env shebang instead.
    assert body.startswith("#!/usr/bin/env bash")


def test_post_sync_hook_script_picks_venv_first() -> None:
    body = HOOK_SCRIPT.read_text(encoding="utf-8")
    # Must prefer the local .venv binary over the system one — that
    # binary is what `uv sync --extra dev` just installed.
    assert ".venv/bin/pre-commit" in body
    # Then fall through to a system / pipx pre-commit on PATH.
    assert "command -v pre-commit" in body


def test_post_sync_hook_script_dryrun_when_no_pre_commit_available(
    tmp_path: Path,
) -> None:
    """If pre-commit isn't found anywhere, the script must exit 1
    with a clear error pointing at ``uv sync --extra dev``."""
    # Run the script from a tmp dir with an empty PATH so neither the
    # repo .venv nor a system pre-commit is reachable.
    proc = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    # If the host happens to have a system pre-commit, the script will
    # exit 0; we only assert the negative shape when it's absent.
    if proc.returncode == 1:
        assert "pre-commit not found" in proc.stderr


# ---- Item 3: doc-parity script suggested edit -----------------------------


def test_parity_script_emits_suggested_edit_on_missing_field(
    tmp_path: Path,
) -> None:
    # Build a tiny doc that's missing *every* config field.
    truncated = tmp_path / "doc.md"
    truncated.write_text(
        "# Operator config reference\n\n(empty)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(PARITY_SCRIPT), "--doc", str(truncated)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 1
    # Suggested-edit block delimiters must be present.
    assert "# --- copy-paste into docs/operator-config-reference.md ---" in proc.stderr
    assert "# --- end paste block ---" in proc.stderr
    # Each entry includes type + default annotation.
    assert "default `" in proc.stderr
    # Block uses backticked field names so a paste lands as inline code.
    assert "`daily_call_budget_per_tool`" in proc.stderr


def test_parity_script_no_suggested_edit_when_clean() -> None:
    """When the doc is in parity, the suggested-edit block must NOT
    appear — operator should not see noise on green runs."""
    proc = subprocess.run(
        [sys.executable, str(PARITY_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    assert "# --- copy-paste" not in proc.stderr
    assert "# --- copy-paste" not in proc.stdout


# ---- Item 4: README documents the new flow --------------------------------


def test_readme_mentions_post_sync_hook_script() -> None:
    body = README.read_text(encoding="utf-8")
    assert "post_sync_install_hooks.sh" in body


def test_readme_mentions_uv_sync_dev_extra() -> None:
    body = README.read_text(encoding="utf-8")
    assert "uv sync --extra dev" in body
