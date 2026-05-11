# Sprint Retro — harbormaster v19.0.0a9

**Phase 6 hotfix** — fixes the v19.0.0a8 Memories tab regression where
the new `memoriesEditor` Alpine component never rendered its content
even though the file list, content, and preview all loaded
successfully under the hood.

## Root cause

Two stacked bugs in the v19.0.0a8 markup:

1. **Broken `x-data` attribute quoting.** The factory binding was
   written as `x-data="memoriesEditor({{ project_name | tojson }})"`,
   which Jinja rendered as `x-data="memoriesEditor("harbormaster")"`.
   The HTML5 parser closed the attribute at the first inner `"`, so
   Alpine saw `x-data="memoriesEditor("` (truncated, syntax error) and
   silently mounted an empty data stack on the section. The `project`
   property was therefore `undefined`, `loadFiles()` never fired
   meaningfully, and the entire reactive system was a no-op.

   The legacy `memoriesPanel` binding had the same shape — it kept
   working only because operators rarely edited memories on multi-
   project pages, so the failure went unnoticed.

   **Fix**: use `x-data="memoriesEditor('{{ project_name | e }}')"` —
   single-quoted string literal interpolation with HTML escaping. This
   sidesteps the double-quote collision entirely.

2. **`x-show` + `x-transition` + `x-data` + `x-init` on the same
   element.** Alpine's transition system sets `style="display: none"`
   inline before evaluating x-show, then x-transition adds enter
   transitions that should remove that inline style. When `x-data` and
   `x-init` are also on the same element, the data initialisation
   races with the transition setup and the inline `display: none`
   never gets cleared on first paint. The section stayed at
   `offsetWidth: 0` indefinitely.

   **Fix**: x-show and x-transition stay on the `<section
   role="tabpanel">`, but x-data + x-init move to a child `<div>`. The
   editor state lives on the inner wrapper; the section just provides
   accessibility metadata and visibility.

## What changed

- `src/harbormaster/ui/templates/project_detail.html` — moved x-data
  and x-init from the Memories tab section onto an inner div, switched
  the project_name interpolation from `| tojson` to `'…' | e`, and
  added a comment block explaining both fixes for future maintainers.
- `tests/ui/test_v19_memories_tab.py` —
  `test_memories_tab_mounts_new_editor_factory` now asserts the new
  single-quoted attribute form,
  `test_memories_editor_section_has_role_tabpanel` now asserts the
  separate-wrapper structure.

## Verified visually

A Playwright capture against the local verifier on port 17800 against
the harbormaster project (which carries 12 `.serena/memories/*.md`
files) shows the editor mounting correctly:

- Left pane lists all 12 memory files with size + tag pills.
- First file (`architecture.md`) auto-selects on load.
- Source markdown populates the textarea (6.2 KB).
- Live preview pane renders the bleach-sanitised HTML (7.7 KB).
- Toolbar exposes Save (greyed out — no edits yet), Undo, Redo, and
  the "diff vs:" dropdown populated with the file's revisions.

## Lesson for the codebase

Every Alpine `x-data` binding that interpolates a Jinja value should
be reviewed for the same quote-collision bug. `trajectoryList` on
project_detail.html has the identical pattern — its `project` ends up
`undefined` too. That bug is pre-existing (not introduced by Phase 6)
and is out of scope for this hotfix, but it should be tracked
separately.

A linter rule — "if x-data contains `{{ … | tojson }}` inside double
quotes, fail" — would have caught both occurrences.
