"""FleetQ ecosystem integration. Optional [fleetq] extra (httpx).

v1.0.0a6 ships the Bridge lifecycle — register, heartbeat, disconnect.
The reverse-WebSocket relay channel for incoming MCP tool calls is
out of scope for a6 and lands in v1.0.0a7+.

See `docs/fleetq-bridge-contract.md` for the discovered FleetQ API contract.
"""
from harbormaster.fleetq.bridge import BridgeClient, BridgeError, RegisterResponse
from harbormaster.fleetq.endpoints import HARBORMASTER_TOOLS, build_manifest
from harbormaster.fleetq.heartbeat import HeartbeatLoop
from harbormaster.fleetq.memory import MemoryWriter
from harbormaster.fleetq.relay import BridgeRelay

__all__ = [
    "HARBORMASTER_TOOLS",
    "BridgeClient",
    "BridgeError",
    "BridgeRelay",
    "HeartbeatLoop",
    "MemoryWriter",
    "RegisterResponse",
    "build_manifest",
]
