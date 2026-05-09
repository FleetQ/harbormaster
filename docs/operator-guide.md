# Harbormaster Operator Guide

Practical guide for deploying, configuring, hardening, and upgrading
Harbormaster in production. Audience: someone responsible for
running Harbormaster either as a personal Bridge daemon or as part
of a multi-user FleetQ deployment.

If you're just trying it out for the first time, start with the
[README](../README.md) Install section instead.

## Contents

1. [Deployment options](#1-deployment-options)
2. [Configuration reference](#2-configuration-reference)
3. [Authentication & authorization](#3-authentication--authorization)
4. [Network exposure & reverse proxies](#4-network-exposure--reverse-proxies)
5. [Logging & monitoring](#5-logging--monitoring)
6. [Upgrades](#6-upgrades)
7. [Troubleshooting](#7-troubleshooting)
8. [systemd / launchd integration](#8-systemd--launchd-integration)

---

## 1. Deployment options

| Mode | When | Install |
|---|---|---|
| **stdio** | Local Claude Code / Desktop integration | `uvx harbormaster-mcp` (or pipx) |
| **HTTP/SSE on loopback** | Local Bridge daemon for FleetQ tunnel | `uvx --prerelease=allow harbormaster-mcp[ui] --transport sse --port 7531` |
| **HTTP/SSE on public bind** | Multi-user / VPS deployment | Loopback-bound + Cloudflare Tunnel / Tailscale Funnel; **never** raw `--host 0.0.0.0` without a token |
| **Docker** | Containerised production | Use the published `harbormaster-mcp` package inside a slim Python image |

`uvx --prerelease=allow harbormaster-mcp` is the fastest path — uvx
manages a per-tool venv automatically. `pipx install --pip-args='--pre'
harbormaster-mcp` works too if you prefer pipx.

For the streaming + Bridge integration features, install with the
`[ui]` and `[fleetq]` extras:

```bash
uvx --prerelease=allow 'harbormaster-mcp[ui,fleetq]' --version
```

## 2. Configuration reference

Config search order (first hit wins):

1. `--config <path>` CLI flag
2. `./.harbormaster.toml` (current working directory)
3. `$XDG_CONFIG_HOME/harbormaster/config.toml` (default
   `~/.config/harbormaster/config.toml`)
4. Built-in defaults

Minimal example (most users):

```toml
[projects]
glob = ["~/htdocs/*"]

[backends.claude]
enabled = true
binary = "claude"
timeout_local = 90
output_word_cap = 800

[hosts.friday]
remote_htdocs = "/home/katsarov/htdocs"
connect_timeout = 10
total_timeout = 120
```

FleetQ Bridge integration:

```toml
[fleetq]
enabled = true
register_as_bridge = true
write_trajectories = true       # opt-in Memory writeback
base_url = "https://app.fleetq.net"
api_token_env = "FLEETQ_API_TOKEN"
heartbeat_interval = 30
```

Set `FLEETQ_API_TOKEN` in the harbormaster process environment to a
Sanctum bearer token with a `team:<uuid>` ability.

Full TOML schema is enforced by Pydantic (`extra = "forbid"`) — typos
fail loudly at startup.

## 3. Authentication & authorization

### MCP HTTP/SSE transport

Always requires a bearer token. The CLI refuses to bind a
non-loopback host (`--host 0.0.0.0`) without one. Set:

```bash
export HARBORMASTER_MCP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
harbormaster-mcp --transport sse --host 127.0.0.1 --port 7532
```

Clients send `Authorization: Bearer <token>` on every request.
Missing or wrong tokens get 401.

### Live UI

Loopback-only by default — no auth needed when bound to 127.0.0.1
because the OS itself enforces "same user only." Setting
`HARBORMASTER_UI_TOKEN` enables opt-in bearer auth on loopback too
(useful for shared dev machines):

```bash
export HARBORMASTER_UI_TOKEN=...
harbormaster-ui --host 127.0.0.1 --port 7531
```

Public bind (`--host 0.0.0.0`) **requires** the token — the CLI
exits with code 2 if it's unset.

### FleetQ Bridge

The token in `FLEETQ_API_TOKEN` is the only credential the bridge
process holds. Rotate via standard FleetQ Sanctum token rotation;
restart the bridge process to pick up the new value.

## 4. Network exposure & reverse proxies

The streaming endpoints (`/mcp/{server}` SSE, `/api/v1/bridge/mcp/call`
on the FleetQ side) require **buffering disabled** at every reverse
proxy in the path. nginx 1.5.6+ honours `X-Accel-Buffering: no` on
`proxy_buffering` by default.

See [`architecture-harbormaster.md` §16](architecture-harbormaster.md)
for the full nginx recipe + verification curl.

Common deployment shapes:

- **Cloudflare Tunnel**: passes `X-Accel-Buffering` through. No
  extra config.
- **Tailscale Funnel**: same. No extra config.
- **nginx in front**: add `proxy_buffering off` to the location
  block + `proxy_read_timeout 300s` (tools take 30-90s).
- **Caddy**: by default streams without buffering. Verify with the
  curl in §16.
- **AWS ALB / Cloudflare Load Balancer**: confirm "streaming
  responses" is enabled.

If your stream looks like one big chunk at the end instead of
incremental output, a proxy is buffering. Add `proxy_buffering off`
(or equivalent) to each layer until `event: chunk` lines appear in
real time.

## 5. Logging & monitoring

`--log-format text` (default) is human-readable. `--log-format json`
emits one JSON object per record — pair with `journalctl`/Docker
log drivers.

Useful log lines to watch for:

- `FleetQ bridge registered: session=…` — successful Bridge handshake
- `FleetQ bridge session lost — re-registering` — heartbeat returned
  404, automatic recovery in progress
- `FleetQ memory writeback rejected: HTTP …` — non-fatal, but worth
  alerting on if you depend on Memory persistence

CI-side checks (recommended):

- The `smoke-mcp-streaming` job in this repo's CI verifies the
  daemon's SSE wire shape on every push. Worth replicating in your
  own deployment's CI.
- The gated `smoke-fleetq` job runs against a real FleetQ if you set
  `FLEETQ_SMOKE_ENABLED=true` + `FLEETQ_TEST_BASE_URL` +
  `FLEETQ_TEST_API_TOKEN` repository variable/secrets.

## 6. Upgrades

Each `v*` git tag triggers a PyPI publish via Trusted Publishing
(no API tokens in the repo). Released versions follow `1.0.0aN`
during the alpha phase; `v1.0.0` GA drops the alpha suffix.

To upgrade a uvx-installed daemon:

```bash
# uvx caches per-tool; refresh:
uvx --refresh --prerelease=allow harbormaster-mcp --version
```

Restart the running daemon (systemd / launchd unit; or `kill $PID`
for a foreground run) to pick up the new code.

For pinned production deployments, pin the version explicitly in
your launcher:

```bash
uvx --prerelease=allow harbormaster-mcp@1.0.0a15 --transport sse ...
```

## 7. Troubleshooting

### `event: chunk` lines arrive only at the end

A reverse proxy in the path is buffering. See §4 +
[architecture §16](architecture-harbormaster.md).

### `invalid-publisher` on PyPI tag push

PyPI Trusted Publisher not registered. See `docs/publishing.md`.
Both prod (`pypi.org`) and `testpypi` need the Trusted Publisher
configured before the workflow can succeed.

### FleetQ Bridge stays "Disconnected" in the FleetQ UI

Heartbeat is hitting the FleetQ side but the daemon's session has
been marked stale. Check:

- `FLEETQ_API_TOKEN` is set correctly in the daemon process
  (`systemctl show <unit> --property=Environment`)
- The token has the right team ability
- The daemon's logs show `FleetQ bridge registered: session=…` at
  startup

### `claude -p` exits non-zero with `not authenticated`

The Anthropic seat for that environment isn't set up. `claude
auth` in the relevant context (local user, SSH host, etc.)
to authenticate.

### Streaming chunks stop mid-stream

Most likely the upstream `claude -p` subprocess died or the
configured `total_timeout` was hit. Check the harbormaster log for
`BackendError(code='exit_nonzero')` or `BackendError(code='timeout')`.

## 8. systemd / launchd integration

### systemd unit (Linux)

```ini
# /etc/systemd/system/harbormaster.service
[Unit]
Description=Harbormaster MCP Bridge daemon
After=network-online.target

[Service]
Type=simple
User=harbormaster
Group=harbormaster
EnvironmentFile=/etc/harbormaster/env
ExecStart=/usr/local/bin/uvx --prerelease=allow 'harbormaster-mcp[ui,fleetq]' --transport sse --host 127.0.0.1 --port 7532
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/harbormaster/env` (chmod 600):

```
HARBORMASTER_MCP_TOKEN=<32-byte token>
FLEETQ_API_TOKEN=<sanctum token>
```

### launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.harbormaster.bridge.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.harbormaster.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/<user>/.local/bin/uvx</string>
    <string>--prerelease=allow</string>
    <string>harbormaster-mcp[ui,fleetq]</string>
    <string>--transport</string><string>sse</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>7532</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HARBORMASTER_MCP_TOKEN</key><string>...</string>
    <key>FLEETQ_API_TOKEN</key><string>...</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/harbormaster.log</string>
  <key>StandardErrorPath</key><string>/tmp/harbormaster.err</string>
</dict>
</plist>
```

`launchctl load ~/Library/LaunchAgents/com.harbormaster.bridge.plist`.

For a long-running daemon on a MacBook used as a server, see the
"clamshell mode" gotcha — user LaunchAgents don't fire when the
display is closed. Use a root LaunchDaemon under
`/Library/LaunchDaemons/` instead, with the user-context unit
kicked by a system-context "kicker" job.

---

For architectural details (module layout, data flow, threading
model), see [`architecture-harbormaster.md`](architecture-harbormaster.md).
For the long-form design rationale, see
[`design-harbormaster.md`](design-harbormaster.md).
