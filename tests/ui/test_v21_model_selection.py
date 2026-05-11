"""v21.0.0a10 — operator-selectable model (--model) wiring tests.

Phase 10 of v21 (replaces the schema-versioning slot per option B):

* ``BackendConfig`` gains ``default_model`` / ``allowed_models`` /
  ``model_aliases`` with safe defaults.
* ``ClaudeBackend._resolve_model`` resolves an optional alias /
  full id through the whitelist; emits ``BackendError("model_not_allowed")``
  on whitelist miss.
* Every entry point (``ask_local`` / ``ask_local_stream`` /
  ``ask_remote`` / ``ask_remote_stream``) accepts the new
  ``model: str | None = None`` kwarg and injects ``--model <id>``
  into the spawned command (or the SSH-shipped command) only when
  resolved is truthy.
* The three streaming MCP tools (``ask_project``, ``delegate_task``,
  ``fan_out_ask``) accept ``model`` and forward it; the UI partials
  render a ``<select x-model="model">`` dropdown.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.backends.claude import ClaudeBackend
from harbormaster.config import BackendConfig, HarbormasterConfig

# ---------- Part A: config defaults ------------------------------------------


def test_backend_config_defaults_have_alias_table() -> None:
    """BackendConfig() picks up the v21.0.0a10 model_aliases defaults
    so a zero-config setup gets haiku / sonnet / opus shorthand for free.
    """
    cfg = BackendConfig()
    assert cfg.default_model is None
    assert cfg.allowed_models == []
    assert cfg.model_aliases["haiku"] == "claude-haiku-4-5-20251001"
    assert cfg.model_aliases["sonnet"] == "claude-sonnet-4-6"
    assert cfg.model_aliases["opus"] == "claude-opus-4-7"


def test_backend_config_accepts_operator_overrides() -> None:
    cfg = BackendConfig(
        default_model="haiku",
        allowed_models=["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        model_aliases={"fast": "claude-haiku-4-5-20251001"},
    )
    assert cfg.default_model == "haiku"
    assert "fast" in cfg.model_aliases


# ---------- Part B: _resolve_model -------------------------------------------


def test_resolve_model_alias_resolves_to_full_id() -> None:
    backend = ClaudeBackend(BackendConfig())
    assert backend._resolve_model("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_model_full_id_passthrough() -> None:
    backend = ClaudeBackend(BackendConfig())
    # Full ids that match no alias are returned verbatim.
    assert backend._resolve_model("claude-opus-4-7") == "claude-opus-4-7"


def test_resolve_model_none_with_no_default_returns_none() -> None:
    backend = ClaudeBackend(BackendConfig())
    assert backend._resolve_model(None) is None


def test_resolve_model_uses_default_when_caller_passes_none() -> None:
    backend = ClaudeBackend(BackendConfig(default_model="sonnet"))
    assert backend._resolve_model(None) == "claude-sonnet-4-6"


def test_resolve_model_caller_overrides_default() -> None:
    backend = ClaudeBackend(BackendConfig(default_model="sonnet"))
    assert backend._resolve_model("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_model_empty_whitelist_accepts_anything() -> None:
    backend = ClaudeBackend(BackendConfig())
    # Whitelist empty → no validation; unknown alias is treated as a
    # literal model id.
    assert backend._resolve_model("some-future-model") == "some-future-model"


def test_resolve_model_rejected_by_whitelist() -> None:
    backend = ClaudeBackend(
        BackendConfig(allowed_models=["claude-haiku-4-5-20251001"])
    )
    with pytest.raises(BackendError) as exc:
        backend._resolve_model("opus")
    assert exc.value.code == "model_not_allowed"
    assert "opus" in str(exc.value)


def test_resolve_model_passes_when_resolved_id_in_whitelist() -> None:
    backend = ClaudeBackend(
        BackendConfig(allowed_models=["claude-haiku-4-5-20251001"])
    )
    # Alias resolution happens BEFORE whitelist check.
    assert backend._resolve_model("haiku") == "claude-haiku-4-5-20251001"


# ---------- Part C: ask_local command wiring --------------------------------


def _make_completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_ask_local_omits_model_flag_when_unspecified(tmp_path: Path) -> None:
    backend = ClaudeBackend(BackendConfig())
    with patch("harbormaster.backends.claude.subprocess.run") as run:
        run.return_value = _make_completed(
            0, '{"result": "ok"}',
        )
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    cmd = run.call_args.args[0]
    assert "--model" not in cmd


def test_ask_local_includes_model_flag_when_alias_passed(tmp_path: Path) -> None:
    backend = ClaudeBackend(BackendConfig())
    with patch("harbormaster.backends.claude.subprocess.run") as run:
        run.return_value = _make_completed(
            0, '{"result": "ok"}',
        )
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1, model="haiku")
    cmd = run.call_args.args[0]
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-haiku-4-5-20251001"


def test_ask_local_includes_model_when_default_model_set(tmp_path: Path) -> None:
    backend = ClaudeBackend(BackendConfig(default_model="opus"))
    with patch("harbormaster.backends.claude.subprocess.run") as run:
        run.return_value = _make_completed(
            0, '{"result": "ok"}',
        )
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    cmd = run.call_args.args[0]
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-opus-4-7"


def test_ask_local_raises_when_model_not_allowed(tmp_path: Path) -> None:
    backend = ClaudeBackend(
        BackendConfig(allowed_models=["claude-haiku-4-5-20251001"])
    )
    with pytest.raises(BackendError) as exc:
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1, model="opus")
    assert exc.value.code == "model_not_allowed"


# ---------- Part D: ask_remote command wiring -------------------------------


def test_remote_command_omits_model_flag_when_unspecified() -> None:
    backend = ClaudeBackend(BackendConfig())
    cmd = backend._build_remote_command("~/htdocs/proj", "hello", 5, model_id=None)
    assert "--model" not in cmd


def test_remote_command_includes_model_flag_with_quoting() -> None:
    backend = ClaudeBackend(BackendConfig())
    cmd = backend._build_remote_command(
        "~/htdocs/proj", "hello", 5,
        model_id="claude-haiku-4-5-20251001",
    )
    assert "--model claude-haiku-4-5-20251001" in cmd


# ---------- Part E: MCP tool signatures -------------------------------------


def test_ask_project_tool_signature_accepts_model() -> None:
    """The MCP tool wrapper must accept ``model`` as a keyword argument
    so MCP clients can pass it through ``arguments.model``.
    """
    import inspect

    from harbormaster.tools.ask import register

    class _Capture:
        def __init__(self) -> None:
            self.fn = None

        def tool(self):
            def wrap(fn):
                self.fn = fn
                return fn
            return wrap

    cap = _Capture()
    register(cap, HarbormasterConfig())  # type: ignore[arg-type]
    sig = inspect.signature(cap.fn)
    assert "model" in sig.parameters
    assert sig.parameters["model"].default is None


def test_delegate_task_tool_signature_accepts_model() -> None:
    import inspect

    from harbormaster.tools.delegate import register

    class _Capture:
        def __init__(self) -> None:
            self.fn = None

        def tool(self):
            def wrap(fn):
                self.fn = fn
                return fn
            return wrap

    cap = _Capture()
    register(cap, HarbormasterConfig())  # type: ignore[arg-type]
    sig = inspect.signature(cap.fn)
    assert "model" in sig.parameters
    assert sig.parameters["model"].default is None


def test_fan_out_ask_tool_signature_accepts_model() -> None:
    import inspect

    from harbormaster.tools.fan_out import register

    class _Capture:
        def __init__(self) -> None:
            self.fn = None

        def tool(self):
            def wrap(fn):
                self.fn = fn
                return fn
            return wrap

    cap = _Capture()
    register(cap, HarbormasterConfig())  # type: ignore[arg-type]
    sig = inspect.signature(cap.fn)
    assert "model" in sig.parameters
    assert sig.parameters["model"].default is None


# ---------- Part F: run_backend passes model through ------------------------


def test_run_backend_forwards_model_to_ask_local(tmp_path: Path, monkeypatch) -> None:
    """run_backend must pass `model` into backend.ask_local so the
    MCP tools (ask_project / delegate_task / fan_out_ask) actually
    drive the resolution."""
    from harbormaster.tools import _helpers as helpers

    captured: dict[str, object] = {}

    class _FakeBackend:
        name = "claude"
        cfg = BackendConfig(output_word_cap=800)

        def ask_local(self, *, cwd, prompt, max_turns, model=None):
            captured["model"] = model
            captured["prompt"] = prompt
            return BackendResult(output="ok", duration_ms=1)

        def ask_remote(self, **kwargs):  # pragma: no cover
            raise AssertionError("should not be called")

    monkeypatch.setattr(
        helpers, "get_backend_for_project", lambda *a, **k: _FakeBackend(),
    )
    monkeypatch.setattr(
        helpers, "resolve_project", lambda *a, **k: tmp_path,
    )
    monkeypatch.setattr(
        helpers, "validate_project_name", lambda *a, **k: None,
    )

    out = helpers.run_backend(
        name="harbormaster",
        prompt="q",
        max_turns=2,
        host=None,
        config=HarbormasterConfig(),
        label_prefix="ask",
        model="sonnet",
    )
    assert out == "ok"
    assert captured["model"] == "sonnet"


# ---------- Part G: UI dropdowns present in templates -----------------------


_ROOT = Path(__file__).resolve().parents[2]


def _read_template(rel: str) -> str:
    return (_ROOT / "src/harbormaster/ui/templates" / rel).read_text(encoding="utf-8")


def test_ask_form_template_has_model_dropdown() -> None:
    html = _read_template("_partials/ask_form.html")
    assert 'x-model="model"' in html
    assert "data-ask-form-model" in html
    assert ">haiku" in html or ">⚡ haiku" in html
    assert ">sonnet" in html or ">⚖ sonnet" in html
    assert ">opus" in html or ">🧠 opus" in html


def test_ask_form_script_has_model_state_and_forwards_arg() -> None:
    js = _read_template("_partials/_ask_form_script.html")
    # State + URL prefill + outbound arg wiring all present.
    assert re.search(r"model:\s*''", js)
    assert "url.searchParams.get('model')" in js
    assert "args.model = this.model" in js


def test_delegate_form_template_has_model_dropdown() -> None:
    html = _read_template("_partials/delegate_form.html")
    assert 'x-model="model"' in html
    assert "data-delegate-form-model" in html
    assert "args.model = this.model" in html


def test_fan_out_template_has_model_dropdown() -> None:
    html = _read_template("fan_out.html")
    assert 'x-model="model"' in html
    assert "data-fanout-form-model" in html
    assert "args.model = this.model" in html


def test_quick_ask_template_has_model_dropdown_and_query_handoff() -> None:
    html = _read_template("dashboard.html")
    # The Quick Ask dropdown + the &model= handoff are both there.
    assert "data-quick-ask-model" in html
    assert "url += '&model=' + encodeURIComponent(this.model)" in html
