"""FleetQ ecosystem integration. Optional [fleetq] extra (httpx).

v1.0.0a6 ships the Bridge lifecycle — register, heartbeat, disconnect.
The reverse-WebSocket relay channel for incoming MCP tool calls is
out of scope for a6 and lands in v1.0.0a7+.

See `docs/fleetq-bridge-contract.md` for the discovered FleetQ API contract.
"""
from harbormaster.fleetq.bridge import BridgeClient, BridgeError, RegisterResponse
from harbormaster.fleetq.dispatcher import (
    DispatcherStats,
    MCPDispatcher,
    current_span_id,
    current_trace_id,
    get_dispatcher_stats,
    span_context,
)
from harbormaster.fleetq.endpoints import HARBORMASTER_TOOLS, build_manifest
from harbormaster.fleetq.heartbeat import HeartbeatLoop
from harbormaster.fleetq.memory import MemoryWriter
from harbormaster.fleetq.relay import BridgeRelay
from harbormaster.fleetq.state import (
    BridgeRuntimeState,
    BridgeRuntimeView,
    BridgeStateWriter,
    read_bridge_state,
)

__all__ = [
    "HARBORMASTER_TOOLS",
    "BridgeClient",
    "BridgeError",
    "BridgeRelay",
    "BridgeRuntimeState",
    "BridgeRuntimeView",
    "BridgeStateWriter",
    "DispatcherStats",
    "HeartbeatLoop",
    "MCPDispatcher",
    "MemoryWriter",
    "RegisterResponse",
    "build_manifest",
    "current_span_id",
    "current_trace_id",
    "get_dispatcher_stats",
    "read_bridge_state",
    "span_context",
]
