# Sprint Retro — harbormaster v21.0.0a5

**Tag:** `v21.0.0a5`
**Phase:** 5 of 10 (v21.0 polish sprint)
**Date:** 2026-05-11
**Theme:** Inspector drag-resize + keyboard shortcuts cheatsheet

## What shipped

### 1. Inspector drag-resize handle
- 4px-wide vertical drag handle anchored to the inspector pane's left edge
  (cursor `col-resize`, hover `bg-accent`, desktop-only via `hidden lg:block`).
- `pointerdown` opens a `pointermove` listener throttled to
  `requestAnimationFrame` so drag stays jank-free under React-shaped
  state churn.
- Width clamped to **[240px, 480px]** with default **320px** (matches the
  v19.0.0a1 baseline). Final width is persisted to
  `localStorage['hm-inspector-width']` on `pointerup`.
- Implementation switches `#hm-shell-grid` from the static Tailwind
  arbitrary class `grid-cols-[240px_1fr_320px]` to an inline `:style`
  binding driven by `appShell().inspectorWidth`. Collapsed branch still
  pins the third column to `0` so the existing collapse toggle keeps
  working unchanged.
- ARIA: handle has `role="separator"` + `aria-orientation="vertical"`
  + `aria-label="Resize inspector"`.

### 2. Keyboard shortcuts cheatsheet
- New `shortcutsCheatsheet()` Alpine scope mounted before `</body>`.
  Opens on **Shift+/ (`?`)**; dismissed by **Esc** or click on scrim.
- Three documented sections:
  - **Global** — `?`, `Esc`, `Cmd+K`, `Cmd+Shift+L`
  - **Project page tabs** — digits 1..5 for the 5 tabs introduced by
    v21.0.0a3 + Q&A history work
  - **Memory editor** — `Cmd+S`, `Cmd+Z`, `Cmd+Shift+Z`
- Modal a11y: `role="dialog"`, `aria-modal="true"`, labelled close
  button, Esc footer hint.
- The same scope hosts the **Cmd/Ctrl+Shift+L** theme-toggle handler
  that flips `theme-light`/`theme-dark` on `<html>` and persists to
  `localStorage['hm-theme']`.
- Input-focus guard: when `INPUT`, `TEXTAREA`, or `contentEditable`
  has focus, the `?` and `Cmd+Shift+L` listeners exit early so typing
  literal `?` in the quick-ask box or memory editor does not hijack
  focus.

## Tests

- `tests/ui/test_v21_drag_resize_and_cheatsheet.py` — 11 new template-
  level assertions (5 drag-resize, 6 cheatsheet) pinning the structural
  contract.
- `tests/ui/test_v21_mobile_drawer.py::test_desktop_grid_layout_preserved`
  updated to assert the new dynamic `grid-template-columns` binding.
- `tests/ui/test_app_shell_layout.py::test_grid_has_three_columns_with_inspector_toggle`
  same update.

## Visual verification

- `/tmp/v21-a5-base.png` — dashboard with default 320px inspector,
  drag handle present in DOM at `aside#inspector [role="separator"]`,
  computed grid columns `240px 720px 320px`.
- `/tmp/v21-a5-cheatsheet.png` — modal panel showing all 3 sections
  with key/action grid, scrim dimming, Esc dismissal hint.

## Operator UX rationale

The fixed 320px inspector was a v19 baseline guess. With v21's denser
SSE traces, memory editor inspector blocks, and Q&A history widgets,
some pages want a wider column while dashboard wants narrower. Drag-
resize gives the operator the lever without a settings round-trip.

The cheatsheet replaces the v6.0.0a4 ad-hoc popover with one panel that
is discoverable (`?` is the universal "help" gesture), complete (all
known shortcuts in one place), and a11y-compliant (modal semantics).

## What's next

Phase 6 of 10 runs next under orchestrator coordination.
