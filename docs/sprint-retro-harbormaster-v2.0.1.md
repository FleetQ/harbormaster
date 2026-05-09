# Sprint Retro — Harbormaster v2.0.1

**Date:** 2026-05-09
**Theme:** First post-GA patch. Four bundled fixes surfaced during a
real cross-host smoke pass: SSH argv quoting, pysher kwarg name,
plugin missing-from-allowlist warning, and a `plugins list` CLI.
Zero behaviour changes for happy-path v2.0.0 deployments.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | fix(v2.0.1): SSH argv quoting + pysher custom_host + plugin warn-missing + plugins list CLI (#22) |

## Capabilities (this sprint)

### 1 · SSH bash -lc argv-quoting fix

OpenSSH joins every positional arg after the host with whitespace
before sending to the remote shell. `["ssh", ..., "friday", "bash",
"-lc", "ls -1 /Users/katsarov/htdocs"]` therefore arrived at the
remote shell as `bash -lc ls -1 /Users/katsarov/htdocs`, and bash
treated `ls` as the -c command with `-1` and `/Users/katsarov/htdocs`
as positional `$0`/`$1`. `ls` ran with no args → listed CWD ($HOME
under a login shell) → every `host=...` MCP tool returned the wrong
directory's contents.

Fix in `build_ssh_argv()`: collapse `bash -lc <cmd>` into a single
argv entry with `shlex.quote(remote_cmd)` so the remote shell sees a
coherent bash invocation. Three regression tests in test_ssh.py
cover whitespace, shell metacharacters, and the empty-command edge.

### 2 · pysher Pusher kwarg name fix

`pysher.Pusher.__init__` exposes the WebSocket host as `custom_host=`,
not `host=`. Wrong kwarg fell through to `**thread_kwargs` →
`Thread.__init__()` → `TypeError`. Symptom: every harbormaster-mcp
boot logged

> Warning: FleetQ bridge relay failed to start
> (Thread.__init__() got an unexpected keyword argument 'host').

Bridge registered + heartbeat fine, but the Reverb WS subscriber
never connected — no inbound MCP calls from FleetQ ever reached
harbormaster.

Fix: rename `host=` to `custom_host=` in `_default_pusher_factory`.
Verified end-to-end against the live FleetQ Reverb (received a real
`pusher:connection_established` event with socket_id). One regression
test mocks `pysher.Pusher` and asserts the factory passes
`custom_host=`.

### 3 · Plugin "in allowlist but not installed" WARNING

Operators that typo `[plugins].allow` or forget `pip install` no
longer silently get zero plugins. After iterating discovered entry
points, `load_plugins()` computes `allowlist - seen_dists` and emits
one WARNING per missing distribution telling the operator how to
fix it (`pip install <name>` or remove from allowlist). Two new
tests cover both the warning path and the all-installed quiet path.

### 4 · `harbormaster-mcp plugins list` introspection CLI

```
$ harbormaster-mcp plugins list
[plugins].enabled = True
[plugins].allow   = ['harbormaster-plugin-hello']
discovered entry points: 1

STATUS              DIST NAME                           ENTRY POINT
--------------------------------------------------------------------------------
loaded              harbormaster-plugin-hello           hello
```

Statuses: `loaded` / `not-allowlisted` / `disabled` / `no-dist-name`
/ `missing`. Mirrors the v2.0.0a2 `reembed` dispatch pattern in
`__main__.main`. Seven new tests in `test_plugins_cli.py`.

## Real numbers

- 0/0 previous-sprint retro action items shipped (this is the first
  post-GA patch — no v2.0.0 retro action items targeted v2.0.1)
- 1 PR opened / merged (#22)
- 13 new tests (3 SSH regressions + 1 pysher + 2 plugin warnings + 7 CLI)
- Test suite: 510 → **520 pass, 1 skip**
- mypy --strict: 45 → 46 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +423 / -3

## What worked

- **Bundled the 4 fixes into one patch release.** All four were
  surfaced from the same end-to-end probe (configure friday host →
  try list_projects → notice wrong contents → trace through ssh →
  notice pysher relay error → notice missing plugin diagnostics).
  Releasing them together as v2.0.1 makes the changelog more
  meaningful than four separate v2.0.x bumps.

- **End-to-end probe BEFORE writing any fix code.** Replaying the
  exact ssh argv harbormaster builds (`ssh ... bash -lc 'ls -1
  /path'` vs the broken multi-arg form) made the bug obvious in
  ~3 minutes. The pysher kwarg bug had the same shape: read the
  upstream signature once, see `custom_host=` vs `host=`, done.

- **Wrapper script + env.sh kept secrets out of git AND CI logs.**
  Token sat in `~/.config/harbormaster/env.sh` (chmod 600); none of
  the test runs leaked it.

- **Regression tests that exercise the actual bug shape.** The SSH
  test asserts the argv has `bash -lc <quoted>` as a single entry;
  the pysher test mocks the import and asserts `custom_host=` is in
  the kwargs. Both fail loudly if anyone reverts.

## What to change / next

- **No CI regression test for `host=...` end-to-end.** The smoke
  matrix doesn't drive the `host=...` path against a real (or fake)
  SSH server. Adding a `mock-ssh-server` fixture would catch this
  shape of bug before it ships.

- **`/api/v1/bridge/broadcasting-auth` returns 404 from FleetQ.net
  prod.** Out of scope for harbormaster, but tracking: the FleetQ
  side of the relay subscribe handshake isn't deployed yet. Once
  it is, the pysher fix unlocks the full inbound path.

## Action items for the next sprint (v2.1.0)

1. **Make the UI useful.** Research report at
   `~/claudedocs/research_harbormaster_ui_2026-05-09.md` lays out a
   six-phase v2.1 alpha sequence: Mermaid graph render +
   bridge/plugin status panels (a1), project detail page (a2),
   recall search inline (a3), "Ask this project" SSE form (a4),
   fan_out + delegate forms (a5), trajectory history (a6) → GA.
   ~22 hours engineering total, all additive (no MCP tool changes).

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- Relay-binary path (Path B)
- `/api/v1/bridge/broadcasting-auth` server-side deployment (FleetQ scope)
- pnpm-lock.yaml / yarn.lock parsers (deferred from v2.0.0a1)
- Parallel cross-host recall via thread pool
