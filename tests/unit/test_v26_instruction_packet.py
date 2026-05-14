"""v26.0.0 — instruction packet builder unit tests."""
from __future__ import annotations

import json
import re

from harbormaster.config import HarbormasterConfig
from harbormaster.instruction import (
    INSTRUCTION_MARKER,
    build_fan_out_packet,
    build_packet,
    execution_mode_for,
    extract_job_id,
    is_instruction_packet,
    packet_kind_for_delegate,
)


def test_packet_contains_marker():
    pkt = build_packet(
        job_id="d_abc",
        kind="delegate-readonly",
        project="alpha",
        cwd="/tmp/alpha",
        host=None,
        prompt="do something",
        max_turns=10,
        model_hint=None,
        allow_writes=False,
        auto_commit=False,
    )
    md = pkt.to_markdown()
    assert INSTRUCTION_MARKER in md
    assert "d_abc" in md
    assert "alpha" in md
    assert "/tmp/alpha" in md


def test_packet_contains_max_turns_and_prompt():
    pkt = build_packet(
        job_id="d_xyz", kind="delegate-writes", project="beta",
        cwd="/tmp/beta", host=None,
        prompt="refactor the auth module",
        max_turns=80, model_hint="haiku",
        allow_writes=True, auto_commit=False,
    )
    md = pkt.to_markdown()
    assert "`80`" in md
    assert "refactor the auth module" in md


def test_packet_agent_options_json_is_parseable():
    pkt = build_packet(
        job_id="d_jsn", kind="ask", project="gamma",
        cwd="/tmp/gamma", host=None,
        prompt="what does this project do?",
        max_turns=5, model_hint="sonnet",
        allow_writes=False, auto_commit=False,
    )
    md = pkt.to_markdown()
    match = re.search(r"```json\n(.+?)\n```", md, re.DOTALL)
    assert match, "agent-options JSON block not found"
    parsed = json.loads(match.group(1))
    assert parsed["subagent_type"] == "general-purpose"
    assert parsed["prompt"] == "what does this project do?"
    assert parsed["max_turns_hint"] == 5
    assert parsed["model_hint"] == "sonnet"


def test_packet_remote_host_marks_remote_cwd_line():
    pkt = build_packet(
        job_id="d_rem", kind="delegate-readonly", project="delta",
        cwd=None, host="friday",
        prompt="status",
        max_turns=10, model_hint=None,
        allow_writes=False, auto_commit=False,
    )
    md = pkt.to_markdown()
    assert "(remote — see host)" in md
    assert "**Host**: `friday`" in md


def test_is_instruction_packet_detector():
    assert is_instruction_packet(f"prefix {INSTRUCTION_MARKER} suffix")
    assert not is_instruction_packet("just some markdown")


def test_extract_job_id_round_trip():
    pkt = build_packet(
        job_id="d_jr_42", kind="delegate-writes", project="z",
        cwd="/tmp/z", host=None, prompt="p",
        max_turns=20, model_hint=None,
        allow_writes=True, auto_commit=False,
    )
    md = pkt.to_markdown()
    assert extract_job_id(md) == "d_jr_42"


def test_extract_job_id_returns_none_on_malformed():
    assert extract_job_id("some random markdown with no marker") is None


def test_packet_kind_for_delegate_resolves_all_combinations():
    assert packet_kind_for_delegate(False, False) == "delegate-readonly"
    assert packet_kind_for_delegate(False, True) == "delegate-readonly"
    assert packet_kind_for_delegate(True, False) == "delegate-writes"
    assert packet_kind_for_delegate(True, True) == "delegate-writes-auto-commit"


def test_execution_mode_for_local_uses_config():
    cfg = HarbormasterConfig()  # default: instruction
    assert execution_mode_for(cfg, host=None) == "instruction"
    assert execution_mode_for(cfg, host="local") == "instruction"


def test_execution_mode_for_remote_always_subprocess():
    cfg = HarbormasterConfig()  # default: instruction
    assert execution_mode_for(cfg, host="friday") == "subprocess"
    # Even with explicit instruction config:
    from harbormaster.config import DelegateConfig
    cfg2 = HarbormasterConfig(delegate=DelegateConfig(execution_mode="instruction"))
    assert execution_mode_for(cfg2, host="friday") == "subprocess"


def test_fan_out_packet_renders_targets_and_marker():
    targets = [
        {"job_id": "d_a", "project": "alpha", "host": "local",
         "cwd": "/tmp/alpha", "prompt": "Q", "max_turns_hint": 3},
        {"job_id": "d_b", "project": "beta", "host": "local",
         "cwd": "/tmp/beta", "prompt": "Q", "max_turns_hint": 3},
    ]
    md = build_fan_out_packet(
        batch_id="batch_xyz", targets=targets,
        synthesize=False, synthesis_max_turns=5, model_hint=None,
    )
    assert INSTRUCTION_MARKER in md
    assert "batch_xyz" in md
    assert "alpha" in md
    assert "beta" in md
    assert "fan-out" in md
    assert "Synthesize**: `False`" in md


def test_fan_out_packet_with_synthesize_flag():
    targets = [{"job_id": "d_a", "project": "x", "host": "local",
                "cwd": "/tmp/x", "prompt": "Q", "max_turns_hint": 3}]
    md = build_fan_out_packet(
        batch_id="batch_synth", targets=targets,
        synthesize=True, synthesis_max_turns=7, model_hint="opus",
    )
    assert "Synthesize**: `True`" in md
    assert "max_turns=7" in md
