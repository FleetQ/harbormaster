"""Live smoke test against a real FleetQ instance.

Round-trips the full Bridge integration:
  register → heartbeat → update_endpoints → disconnect

Gated by env vars; not part of the default pytest suite. Run locally:

    FLEETQ_TEST_BASE_URL=http://host.docker.internal:8088 \\
    FLEETQ_TEST_API_TOKEN=$(...) \\
    uv run python tests/smoke_fleetq.py

In CI, this is invoked by the `smoke-fleetq` job in `.github/workflows/ci.yml`
when the `FLEETQ_SMOKE_ENABLED` repository variable is set to `true` and the
matching secrets are configured.

Exit codes:
  0  full round trip succeeded
  2  required env vars missing
  1  any HTTP / assertion failure with details on stderr
"""

from __future__ import annotations

import os
import sys
import traceback

from harbormaster.fleetq.bridge import BridgeClient


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: {name} is required for the live smoke test", file=sys.stderr)
        sys.exit(2)
    return value


def main() -> int:
    base_url = _require_env("FLEETQ_TEST_BASE_URL")
    api_token = _require_env("FLEETQ_TEST_API_TOKEN")

    initial_endpoints = {
        "mcp_servers": [{"name": "harbormaster"}],
    }
    updated_endpoints = {
        "mcp_servers": [
            {"name": "harbormaster"},
            {"name": "harbormaster-smoke-extra"},
        ],
    }

    client = BridgeClient(
        base_url=base_url,
        api_token=api_token,
        label="harbormaster-ci-smoke",
    )
    print(f"base_url={base_url}  session_id={client.session_id}")

    try:
        resp = client.register(initial_endpoints)
        if resp.session_id != client.session_id:
            print(
                f"FAIL register: session_id roundtrip mismatch "
                f"({resp.session_id!r} vs {client.session_id!r})",
                file=sys.stderr,
            )
            return 1
        if not resp.team_id:
            print("FAIL register: response did not include team_id", file=sys.stderr)
            return 1
        print(f"OK register: team_id={resp.team_id}")

        if not client.heartbeat():
            print(
                "FAIL heartbeat: returned False immediately after register "
                "(session lost?)",
                file=sys.stderr,
            )
            return 1
        print("OK heartbeat")

        client.update_endpoints(updated_endpoints)
        print("OK update_endpoints")

        # Repeat heartbeat after update_endpoints — verifies the session is still
        # known after the manifest refresh.
        if not client.heartbeat():
            print(
                "FAIL heartbeat-after-update: session lost after update_endpoints",
                file=sys.stderr,
            )
            return 1
        print("OK heartbeat-after-update")

        removed = client.disconnect()
        if removed != 1:
            print(
                f"FAIL disconnect: expected 1 disconnected connection, got {removed}",
                file=sys.stderr,
            )
            return 1
        print(f"OK disconnect: removed {removed}")
    except Exception:
        print("UNEXPECTED EXCEPTION during smoke run:", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        client.close()

    print("SMOKE PASSED — full FleetQ Bridge round trip complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
