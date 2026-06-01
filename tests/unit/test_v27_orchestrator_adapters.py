"""v27.0.0 — orchestrator adapter rendering."""
from __future__ import annotations

import pytest

from harbormaster.instruction import (
    INSTRUCTION_MARKER,
    build_fan_out_packet,
    build_packet,
)
from harbormaster.orchestrators import (
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
    NeutralAdapter,
    OrchestratorAdapter,
    get_adapter,
    register_adapter,
)


def _packet(**overrides):
    base = {
        "job_id": "d_abc",
        "kind": "delegate-readonly",
        "project": "myproj",
        "cwd": "/home/u/htdocs/myproj",
        "host": None,
        "prompt": "Do the thing.",
        "max_turns": 10,
        "model_hint": None,
        "allow_writes": False,
        "auto_commit": False,
    }
    return build_packet(**{**base, **overrides})


def test_claude_adapter_packet_is_byte_for_byte_to_markdown():
    p = _packet()
    assert ClaudeAdapter().render_packet(p) == p.to_markdown()


def test_claude_adapter_fan_out_is_byte_for_byte():
    targets = [{"job_id": "d1", "project": "a", "cwd": "/a", "prompt": "x"}]
    assert ClaudeAdapter().render_fan_out(
        batch_id="batch_1",
        targets=targets,
        synthesize=False,
        synthesis_max_turns=5,
        model_hint=None,
    ) == build_fan_out_packet(
        batch_id="batch_1",
        targets=targets,
        synthesize=False,
        synthesis_max_turns=5,
        model_hint=None,
    )


@pytest.mark.parametrize("adapter", [CodexAdapter(), GeminiAdapter(), NeutralAdapter()])
def test_non_claude_packet_has_core_contract(adapter):
    p = _packet()
    out = adapter.render_packet(p)
    assert INSTRUCTION_MARKER in out
    assert p.job_id in out
    # cwd embedded in body (no per-delegation cwd arg in codex/gemini)
    assert p.cwd in out
    # report-back via harbormaster's own tool
    assert "record_delegation_result" in out
    assert p.prompt in out


@pytest.mark.parametrize("adapter", [CodexAdapter(), GeminiAdapter(), NeutralAdapter()])
def test_non_claude_packet_has_no_claude_isms(adapter):
    out = adapter.render_packet(_packet())
    assert "subagent_type" not in out
    assert "Task tool" not in out


def test_gemini_uses_generalist_idiom():
    out = GeminiAdapter().render_packet(_packet())
    assert "@generalist" in out


def test_codex_uses_spawn_idiom():
    out = CodexAdapter().render_packet(_packet())
    assert "spawn" in out.lower()


@pytest.mark.parametrize("adapter", [CodexAdapter(), GeminiAdapter(), NeutralAdapter()])
def test_writes_packet_surfaces_cwd_path(adapter):
    # Highest-consequence constraint: a write-enabled non-Claude delegation
    # must surface the project path somewhere the orchestrator can act on,
    # since these CLIs take no per-delegation cwd argument.
    p = _packet(kind="delegate-writes", allow_writes=True)
    out = adapter.render_packet(p)
    assert p.cwd in out


def test_neutral_carries_json_descriptor():
    out = NeutralAdapter().render_packet(_packet())
    assert "```json" in out
    assert '"report_back_tool": "record_delegation_result"' in out


def test_writes_clause_reflects_flags():
    ro = CodexAdapter().render_packet(_packet(allow_writes=False))
    assert "Read-only" in ro
    writes = CodexAdapter().render_packet(
        _packet(kind="delegate-writes", allow_writes=True),
    )
    assert "must NOT git-commit" in writes
    commit = CodexAdapter().render_packet(
        _packet(
            kind="delegate-writes-auto-commit",
            allow_writes=True,
            auto_commit=True,
        ),
    )
    assert "git-commit" in commit


def test_get_adapter_resolves_known_names():
    assert isinstance(get_adapter("claude"), ClaudeAdapter)
    assert isinstance(get_adapter("codex"), CodexAdapter)
    assert isinstance(get_adapter("gemini"), GeminiAdapter)
    assert isinstance(get_adapter("neutral"), NeutralAdapter)


def test_get_adapter_unknown_is_none():
    assert get_adapter("bogus") is None
    assert get_adapter("") is None


def test_register_adapter_plugin_seam():
    class FakeAdapter:
        name = "fake_v27_test"

        def render_packet(self, packet):
            return "FAKE"

        def render_fan_out(self, **_):
            return "FAKE_FANOUT"

    adapter: OrchestratorAdapter = FakeAdapter()
    register_adapter(adapter)
    try:
        got = get_adapter("fake_v27_test")
        assert got is adapter
        assert got.render_packet(_packet()) == "FAKE"
    finally:
        from harbormaster import orchestrators as _o
        _o._ORCHESTRATOR_ADAPTERS.pop("fake_v27_test", None)
