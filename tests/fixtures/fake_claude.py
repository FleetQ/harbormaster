#!/usr/bin/env python3
"""Fake `claude` binary used by Harbormaster e2e tests.

Mimics the subset of the `claude -p` interface that harbormaster spawns:

    claude -p \\
      --permission-mode bypassPermissions \\
      --max-turns N \\
      --output-format json \\
      <prompt>

Writes a JSON `{"result": "..."}` payload to stdout. Used by
tests/integration/test_e2e_fake_claude.py to exercise the real subprocess
spawn / JSON parse path without consuming an Anthropic seat in CI.

Failure modes (selected via env var `HARBORMASTER_FAKE_CLAUDE_FAIL`):

    timeout   sleep so caller's timeout fires
    exit2     exit code 2 + stderr 'simulated failure'
    garbage   non-JSON output
    empty     {"result": ""} → triggers parse_failure

The default mode echoes the prompt + cwd into the result field so tests
can assert that harbormaster passed them through correctly.
"""
from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    fail = os.environ.get("HARBORMASTER_FAKE_CLAUDE_FAIL", "")

    if fail == "timeout":
        # Sleep longer than any reasonable test timeout. Caller should kill us.
        time.sleep(120)
        return 0
    if fail == "exit2":
        print("simulated failure", file=sys.stderr)
        return 2
    if fail == "garbage":
        sys.stdout.write("this is not json at all\n")
        return 0
    if fail == "empty":
        json.dump({"result": ""}, sys.stdout)
        return 0

    # Default success path: echo prompt + cwd into the result field.
    # Last positional argv is the prompt (per the real claude -p interface).
    prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
    cwd = os.getcwd()
    canned = f"FAKE_CLAUDE answered prompt={prompt!r} from cwd={cwd}"

    json.dump({"result": canned}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
