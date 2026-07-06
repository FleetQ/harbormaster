"""The FleetQ bridge + auto-reembed background subsystems must not run on the
stdio transport by default.

Regression guard for the field incident where each Claude Desktop / Code
connection spawned a fresh stdio ``harbormaster-mcp`` that started its own
FleetQ bridge heartbeat loop — producing duplicate registrations, a 30s
heartbeat-retry loop that filled the client's stderr (5MB+), and orphaned
daemon threads when the client closed the pipe.
"""
from __future__ import annotations

from unittest import mock

from harbormaster.__main__ import main
from harbormaster.config import HarbormasterConfig


def _run_main(argv: list[str], config: HarbormasterConfig):
    """Invoke main() with the heavy edges patched out.

    Returns the ``_maybe_start_fleetq_bridge`` and auto-reembed mocks so the
    caller can assert whether the background subsystems were started.
    """
    reembed = mock.MagicMock()
    with (
        mock.patch("harbormaster.__main__.load_config", return_value=config),
        mock.patch("harbormaster.__main__.build_server") as build,
        mock.patch(
            "harbormaster.__main__._maybe_start_fleetq_bridge"
        ) as bridge,
        mock.patch(
            "harbormaster.history.maybe_start_auto_reembed_thread", reembed
        ),
        mock.patch(
            "harbormaster.transport.require_auth_token_or_exit",
            return_value="tok",
        ),
        mock.patch("harbormaster.transport.run_http_transport"),
    ):
        # stdio path calls mcp.run(); http path is fully patched above.
        build.return_value.run = mock.MagicMock()
        rc = main(argv)
    return rc, bridge, reembed


def test_stdio_does_not_start_bridge_or_reembed():
    rc, bridge, reembed = _run_main([], HarbormasterConfig())
    assert rc == 0
    bridge.assert_not_called()
    reembed.assert_not_called()


def test_stdio_with_opt_in_starts_background_subsystems():
    config = HarbormasterConfig.model_validate({"fleetq": {"bridge_in_stdio": True}})
    rc, bridge, reembed = _run_main([], config)
    assert rc == 0
    bridge.assert_called_once()
    reembed.assert_called_once()


def test_http_transport_starts_background_subsystems():
    rc, bridge, reembed = _run_main(
        ["--transport", "streamable-http", "--port", "0"], HarbormasterConfig()
    )
    assert rc == 0
    bridge.assert_called_once()
    reembed.assert_called_once()
