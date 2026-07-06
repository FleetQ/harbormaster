"""The MCP server exposes orientation instructions to the calling client,
including the long-poll timeout guidance that prevents interactive clients
(Claude Desktop / claude.ai) from hanging await_* calls past their tool-result
window."""
from __future__ import annotations

from harbormaster.config import HarbormasterConfig
from harbormaster.server import SERVER_INSTRUCTIONS, build_server


def test_instructions_cover_core_workflow_and_timeout_pitfall():
    text = SERVER_INSTRUCTIONS.lower()
    # Core delegate→await workflow is named.
    assert "delegate_task" in text
    assert "await_inbox" in text or "await_delegated_task" in text
    # The interactive-client long-poll guidance is present (the actual pain point).
    assert "timeout_seconds" in text
    assert "claude desktop" in text


def test_build_server_wires_instructions():
    mcp = build_server(HarbormasterConfig())
    assert mcp.instructions == SERVER_INSTRUCTIONS
