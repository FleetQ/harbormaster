# Test plan — v2.1 UI sprint

Per-phase test coverage. Each phase ships PR-green; existing 520
tests stay green throughout.

## Common patterns

- FastAPI `TestClient` against `harbormaster.ui.app.create_app(config)`
- HTML assertions: `assert "selector" in response.text` (no headless
  browser; we trust Tailwind/Alpine/Mermaid behaviour)
- New JSON endpoints: schema + sample-response assertions
- SSE: probe with `httpx` client, parse first 1–2 chunks; don't
  drive a full Claude run from CI

## Phase a1 — Mermaid graph + bridge/plugin status

| Test | What it asserts |
|------|-----------------|
| `test_dashboard_includes_mermaid_cdn` | base.html or dashboard.html has the mermaid script tag |
| `test_dashboard_renders_graph_div` | `<div class="mermaid">` present with non-empty markup |
| `test_api_bridge_status_returns_disconnected_when_fleetq_off` | endpoint exists; reports state |
| `test_api_bridge_status_returns_session_id_when_registered` | with monkey-patched heartbeat state |
| `test_api_plugins_returns_status_table` | matches plugins_cli categorization |
| `test_api_plugins_handles_empty_allowlist` | no errors on minimal config |

## Phase a2 — Project detail page

| Test | What it asserts |
|------|-----------------|
| `test_project_detail_renders_for_known_project` | returns 200 + project name in HTML |
| `test_project_detail_returns_404_for_unknown` | returns 404 with helpful message |
| `test_project_detail_shows_git_log` | last commit hash + subject |
| `test_project_detail_shows_serena_memories` | memory file names |
| `test_project_detail_renders_for_remote_host` | `?host=friday` works |
| `test_dashboard_card_links_to_detail_page` | href attribute pattern |

## Phase a3 — Recall search inline

| Test | What it asserts |
|------|-----------------|
| `test_dashboard_has_recall_search_input` | input element + Alpine binding |
| `test_recall_via_dashboard_returns_matches` | end-to-end: seed store, search, get matches |
| `test_recall_with_no_results_shows_empty_state` | UX safety net |

## Phase a4 — "Ask this project" SSE form

| Test | What it asserts |
|------|-----------------|
| `test_project_detail_has_ask_form` | form element + textarea + button |
| `test_ask_form_token_query_param_supported` | route accepts `?token=` for EventSource |
| `test_ask_form_streams_chunks_via_sse` | smoke: fake claude backend yields chunks; consumer receives them |
| `test_ask_form_handles_backend_error` | error event delivered to client |

## Phase a5 — fan_out + delegate forms

| Test | What it asserts |
|------|-----------------|
| `test_fan_out_page_renders_project_chips` | dashboard projects appear as multi-select |
| `test_fan_out_concurrency_default_is_5` | matches MCP tool default |
| `test_fan_out_post_dispatches_via_sse` | end-to-end smoke |
| `test_delegate_form_has_deliverable_field` | form structure |

## Phase a6 — Trajectory history

| Test | What it asserts |
|------|-----------------|
| `test_api_trajectories_filter_by_project` | returns recent rows, sorted desc |
| `test_api_trajectories_respects_limit` | default + override |
| `test_api_trajectories_returns_empty_for_unknown_project` | no errors |
| `test_history_view_renders_collapsible_pairs` | UX selectors |

## Pass criteria per phase

- All new tests pass
- Existing 520 baseline stays green
- mypy --strict clean across new files
- ruff clean
- CI matrix (Ubuntu+macOS × py3.11/3.12/3.13) green
- Smoke jobs green (smoke-ui especially, since it boots the dashboard)

## Out of scope (won't test)

- Headless browser interaction (JS event handlers exercised via
  selector assertions only)
- Real claude `-p` invocations against real projects (already
  smoke-tested in `test_e2e_fake_claude.py`)
- Live FleetQ Reverb behaviour (already covered in `test_relay.py`)
- Mermaid rendering correctness (CDN library; trust upstream)
