# Sprint Retro — Harbormaster v14.0.0a6

**Date:** 2026-05-10
**Theme:** Architectural extension — cross-host plugin discovery via SSH.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `e025ddc` | feat(v14.0.0a6): cross-host plugin discovery via SSH |

## Capabilities (this sprint)

### 1 · `harbormaster-mcp plugins list --json`

The existing v2.0.1 `plugins list` CLI grew a `--json` flag that
emits a single JSON object with the same schema as
`GET /api/plugins`:

```json
{
  "enabled": true,
  "allow": ["foo-plugin"],
  "discovered_count": 1,
  "plugins": [
    {"status": "loaded", "dist_name": "foo-plugin", "entry_point": "foo"}
  ]
}
```

Text output is preserved byte-for-byte without `--json` (back-compat
contract). Refactored the shared logic into `_list_payload()` so the
JSON CLI and HTTP endpoint can never drift.

### 2 · `query_remote_plugins(host_cfg)`

New helper in `harbormaster.plugins` that SSHs to `host_cfg.ssh_host`
using `harbormaster.ssh.run_ssh` (same `BatchMode=yes` /
`connect_timeout` / `total_timeout` knobs as `backends/claude.py`)
and runs `harbormaster-mcp plugins list --json` on the remote. The
JSON is parsed and returned.

Failure handling — never raises, always returns the same envelope
shape with an `error` key:

* SSH timeout → `{..., "error": "SSH to '...' exceeded Ns"}`
* SSH-layer failure (refused, host-key, perm) → diagnose_ssh_failure msg
* Remote non-zero exit (e.g. binary missing) → `rc=N: <last stderr line>`
* Invalid JSON / non-dict → explicit message

This makes the caller side trivial — just render the envelope; the
UI shows `error` as a warning line and the empty `plugins: []`.

### 3 · `GET /api/plugins?host=<name>`

Endpoint accepts an optional `host` query param:

* Unset / `local` → existing v2.1.0a1 local discovery (byte-identical)
* Configured host name → dispatch to `query_remote_plugins`
* Unknown host → 404

Dashboard plugin card grows a host filter dropdown (populated from
the v14.a4 `/api/hosts/budget` endpoint, which already returns
configured host names — no new endpoint needed). The remote-error
envelope renders as a yellow warning line above the (empty) plugin
list, so an SSH-down host shows up immediately.

## Real numbers

- 2/2 v14.a5 sprint-plan items shipped (the action item was singular —
  cross-host plugins; this also ships --json and the UI dropdown as
  required substeps)
- 1 commit, 6 files changed (1 plugin module, 1 CLI, 1 routes, 1
  template, 2 test files)
- 17 new tests in `tests/unit/test_v14_cross_host_plugins.py`:
  - CLI JSON shape (3 — JSON output, text-format unchanged, helper)
  - SSH-mocked query function (5 — happy path, timeout, ssh fail,
    remote nonzero, invalid JSON)
  - `/api/plugins?host=…` endpoint dispatch (4 — local default,
    `host=local`, 404 unknown, remote dispatch)
  - UI wiring (5 — dropdown markup, budget endpoint reuse, host
    param appending, remote-error envelope render, state init)
- Updated `test_state_badges.py` window for the new dropdown markup
- Test suite delta: 1411 → 1428 passed
- Lint: ruff clean. Type-check: `mypy --strict` clean (57 source files)
- Backwards-incompatible changes: 0 (--json is opt-in, ?host= is
  optional, dropdown hidden when no hosts configured)

## What worked

- **Reusing `/api/hosts/budget` for the host dropdown.** Saved a
  whole new `/api/hosts` endpoint. The budget endpoint already
  returns `{hosts: [{host: "alpha", ...}, ...]}` which is exactly
  the shape the dropdown needs. Two-feature reuse from one endpoint.
- **`_list_payload()` extraction.** Without the helper, the CLI's
  `_list` and the HTTP endpoint's `api_plugins` would have drifted
  on the next field addition. One source of truth + JSON shape
  asserted in tests.
- **Envelope-with-error pattern over exceptions.** Means the UI
  doesn't need a try/catch wrapper around `loadPlugins()` for the
  remote case — it just renders `plugins.error` if present. Same
  pattern as the v8.a3 canonical empty-state markup.

## What to change / next

- **`harbormaster.ssh.run_ssh` mock target gotcha.** First test
  pass mocked `harbormaster.plugins.run_ssh` (the local import in
  `query_remote_plugins`) — `mock.patch` caught that as
  AttributeError. Real fix: mock the source location
  (`harbormaster.ssh.run_ssh`). Worth a brief note in the testing
  conventions memory next time we touch it.
- **No remote `[hosts.<label>]` config validation against the
  dropdown.** A typo in the host name in `?host=foo` returns 404,
  but the operator might wonder whether it's a config typo or an
  SSH failure. Future polish: surface the config-source for the
  dropdown options ("from `[hosts.alpha]`").

## Action items for v14.0.0 GA

The GA bump captures all six alphas in a cumulative retro covering
the v14 sprint shape, plus the v15 candidate list.

## Out-of-scope (still)

- Recursive cross-host plugin discovery (host A → host B → host C).
  Not a real operator workflow.
- Concurrent multi-host queries (e.g. `?host=all`). The single-host
  pattern is enough for the dashboard card; if multi-host comes up
  we can fan_out via the existing dispatcher.
- Local-side caching of remote results. Each dropdown change is one
  SSH RTT; acceptable for an interactive toggle.
