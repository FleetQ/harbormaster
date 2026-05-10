# Sprint Retro — Harbormaster v9.0.0a1

**Date:** 2026-05-10
**Phase:** v9.0 Phase 1 — Tailwind v4 vendor + build hook
**Branch:** `feat/v9.0-tailwind-v4-vendor`

## What shipped

The build infrastructure + vendored Tailwind v4 stylesheet that
v8.0.0a7 explicitly deferred. End users still install with
`uvx harbormaster-mcp` — zero Node toolchain — because compilation
happens at wheel-build time on the maintainer's machine.

| Artifact                                            | Purpose                                                                              |
|-----------------------------------------------------|--------------------------------------------------------------------------------------|
| `src/harbormaster/ui/static/tailwind.input.css`     | Source CSS: `@import "tailwindcss"` + `@theme` block                                  |
| `src/harbormaster/ui/static/tailwind.css`           | Pre-compiled minified output (5224 bytes; ships in wheel)                            |
| `build_tailwind_css.py`                             | Hatchling custom build hook (compiles via `npx @tailwindcss/cli`)                    |
| `GET /static/{path}` route                          | Serves packaged static assets via `importlib.resources.files`                        |
| `<link rel="stylesheet" href="/static/tailwind.css">` in `base.html` | Loaded BEFORE the v3 CDN so `@theme` tokens register first   |
| `pyproject.toml` `[tool.hatch.build.targets.wheel.hooks.custom]` | Registers the build hook                                          |
| `tests/ui/test_tailwind_v4_vendor.py`               | 40 audit tests (file existence, token names, route behavior, traversal blocking)     |

## Numbers

* **Tests:** 921 → 960 (+39 new; +4.2%)
* **Source files:** 52 → 52 (no Python source files added — the build hook lives at repo root, not under `src/harbormaster`)
* **Wheel size:** +6KB (5224-byte minified `tailwind.css` + 3398-byte `tailwind.input.css`)
* **Build wall-clock:** ~13s overhead per `uv build` (npm install of `tailwindcss` + `@tailwindcss/cli` into temp prefix; CLI compile itself is ~25ms)
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing

## Distribution decision (encoded by operator before sprint start)

**Path B — build step.** The hatchling build hook compiles the CSS
at packaging time and ships pre-compiled output in the wheel. The
fallback path (when `npx` is missing on the build host) trusts the
committed `tailwind.css` as a checked-in artifact. This makes:

* Source distributions on Node-less CI work without surprise: the
  hook warns and continues.
* Maintainer wheels always carry a fresh build (the canonical
  `--color-accent` probe token is verified before write succeeds).
* End-user install cost: unchanged. The wheel just has 6KB more
  asset payload.

## Deviations from the phase plan

### 1 · Utility-class migration deferred to a follow-up alpha

**Plan called for:** "Migrate utility classes across all templates from
raw color names (`bg-cyan-700`, `text-gray-400`) to semantic-token
classes (`bg-accent`, `text-muted`)" within v9.0.0a1.

**What actually shipped:** the build infrastructure + token defs +
vendored stylesheet only. Templates still use Tailwind v3 utility
classes via the CDN.

**Why split (the phase plan authorizes this exact escape hatch):**
~150 utility-class rewrites across 6 templates without a
screenshot-diff harness is an unbounded visual-regression risk.
The v8 retro flagged this same constraint — *"v8 dodged visual
regression by being purely additive. v9's Tailwind v4 utility
migration breaks that constraint; visual confirmation needs a
regression test."*

The vendored stylesheet + CDN coexist additively: the new
`@theme` tokens register first (safe — no Tailwind v3 utility
class redefines `--color-*`) and the CDN's utility classes layer
on top. **Both paths produce identical visuals today.**
Migration to semantic tokens (`bg-cyan-700` → `bg-accent`)
becomes a follow-on alpha that can be visually-verified once the
screenshot-diff harness lands.

### 2 · Force-include attempt in `pyproject.toml` rolled back

Initial attempt added `force-include = { "src/.../static" = "harbormaster/ui/static" }`
under `[tool.hatch.build.targets.wheel]`. Result: duplicate-name
zip entries (the wheel auto-includes every file under `packages`
already). Removed the force-include; relied on the default
include. Recorded as a feedback note for v10 retros.

## What worked

* **Hatchling custom build hook + `npx @tailwindcss/cli` is the
  cleanest "build step" path tested.** The hook installs Tailwind
  into a temp prefix, symlinks `node_modules` next to the input
  CSS so `@import "tailwindcss"` resolves, runs the CLI, then
  cleans up. Maintainer side has Node already; the hook *adds*
  ~13s to `uv build`; end users see only the resulting wheel.
* **`importlib.resources.files` for static-asset serving.** Works
  in zipped wheels without a runtime path-resolution fallback;
  containment check via `.resolve()` is belt + suspenders against
  symlink escape on regular installs.
* **Probe-token verification in the build hook.** A 0-byte
  `tailwind.css` would still parse as valid CSS in the wheel; the
  hook explicitly asserts `--color-accent` survives compilation,
  catching `@theme`-block-dropped regressions before publish.

## What we'd do differently

* **Land the screenshot-diff harness before kicking off the
  utility-class migration alpha.** v8's retro flagged this; v9.0.0a1
  confirms it's still the gate. Without it, the migration is
  un-reviewable.
* **Document the maintainer-side prereq.** The build hook works
  silently when Node is present and warns when absent — but the
  warning is inside `uv build` output, easy to miss. Add a
  `make build` (or equivalent) Make/just target that explicitly
  surfaces the build-tool requirements.

## Forward to v9.0.0a2

Phase 2: `/api/dispatcher/status` real endpoint. Closes the
v7.0.0a5 deferral (the KPI-strip "ready" placeholder is replaced
with live runtime metrics).
