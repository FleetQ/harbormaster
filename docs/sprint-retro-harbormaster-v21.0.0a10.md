# v21.0.0a10 — Model selection per MCP tool call

**Date:** 2026-05-11
**Theme:** Operator-selectable model (`haiku` / `sonnet` / `opus`) at call time.
**Slot:** Replaces the originally-planned schema-versioning phase per operator's "option B" choice during chain — schema versioning permanently deferred until first breaking shape change.

## What shipped

### Backend layer (`backends/claude.py` + `codex.py`)

- `_resolve_model()` helper: maps shorthand alias → full model id via `BackendConfig.model_aliases`; validates against `allowed_models` whitelist (empty list = no whitelist).
- `ask_local`, `ask_local_stream`, `ask_remote`, `ask_remote_stream` all gained `model: str | None = None` kwarg.
- When `model` is non-None and resolves to a real id, `--model <id>` is appended to the `claude -p` command (and shell-quoted on the remote path).
- When `model=None` and no `default_model` config, no `--model` flag is passed — backend retains its own default behavior.
- `Backend` protocol in `backends/base.py` extended with the new `model` kwarg so mypy --strict is happy across `tools/*` callers.

### Config (`config.py`)

`BackendConfig` extended with three opt-in fields:
- `default_model: str | None = None` — applied when caller omits `model`.
- `allowed_models: list[str] = []` — empty = no validation; non-empty = whitelist gate.
- `model_aliases: dict[str, str]` — default ships `haiku` → `claude-haiku-4-5-20251001`, `sonnet` → `claude-sonnet-4-6`, `opus` → `claude-opus-4-7`. Operator can override per backend.

### MCP tool signatures (`tools/ask.py`, `delegate.py`, `fan_out.py`)

- `ask_project(name, question, max_turns=5, host=None, model=None)`
- `delegate_task(name, task, deliverable, allow_writes=False, host=None, model=None)`
- `fan_out_ask(question, project_filter=None, host_filter=None, max_concurrency=5, max_turns=3, model=None)`
- MCP tool descriptions advertise the parameter so MCP clients see it in their tool listings.

### UI surface

- Ask form (`_partials/ask_form.html` + `_ask_form_script.html`): `<select x-model="model">` with options `auto / ⚡ haiku / ⚖ sonnet / 🧠 opus`.
- Delegate form: same dropdown.
- Fan-out form: same dropdown (visible in screenshot — "model: auto" next to `max_concurrency` / `max_turns` / `host`).
- Quick Ask on dashboard: appends `&model=<value>` to project page URL when non-auto; project page reads the param for prefill.

## Tests

`tests/ui/test_v21_model_selection.py` — 25 new tests:
- `BackendConfig` accepts and defaults new fields
- Alias resolution roundtrip
- Whitelist enforcement raises `BackendError("model_not_allowed")`
- `ask_local` / `ask_remote` build subprocess args with `--model <id>` when supplied
- MCP tool layer passes `model` through to backend
- UI templates contain the dropdown markup on three forms

All 25 pass. mypy `--strict` clean, ruff clean.

## Visual verification

`/tmp/v21-a10-fanout-with-model.png` — "model auto" dropdown visible in fan-out form between `host` and `Targets` panel.

`/tmp/v21-a10-ask-form-with-model.png` — same dropdown in project page Overview ask form.

## Operator note

Schema versioning for `dispatcher status --json` (the originally-planned a10) is **permanently deferred**. The chain decision: ship visible operator value (model selection) over invisible infrastructure (schema versioning until a real breaking change forces it). No external consumer of the JSON shape was identified.

## Files modified

- `src/harbormaster/config.py` — `BackendConfig` extension
- `src/harbormaster/backends/base.py` — Protocol signature
- `src/harbormaster/backends/claude.py` — `_resolve_model` + cmd builder
- `src/harbormaster/backends/codex.py` — mirror
- `src/harbormaster/tools/ask.py` — tool signature + pass-through
- `src/harbormaster/tools/delegate.py` — same
- `src/harbormaster/tools/fan_out.py` — same
- `src/harbormaster/tools/_helpers.py` — `make_*_backend_stream` model kwarg plumbing
- `src/harbormaster/ui/routes.py` — Quick Ask + form pre-fill
- `src/harbormaster/ui/templates/_partials/ask_form.html` + `_ask_form_script.html`
- `src/harbormaster/ui/templates/_partials/delegate_form.html`
- `src/harbormaster/ui/templates/dashboard.html` — Quick Ask URL builder
- `src/harbormaster/ui/templates/fan_out.html` — dropdown
- `tests/ui/test_v21_model_selection.py` — new (25 tests)
