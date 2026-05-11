"""v19.0.0a6: full Memories tab implementation (split-pane editor).

Pins the structural invariants of the new memoriesEditor Alpine
component on project_detail.html:

  - The v19.a2 placeholder banner ("full implementation lands in
    v19.0.0a6.") is gone.
  - The legacy memoriesPanel viewer/editor block is wrapped in
    `{% if false %}` so it never renders (kept inert as an artefact,
    will be deleted entirely once the new editor has soaked).
  - The new memoriesEditor binds at the Memories tab section root
    via x-data + x-init.
  - File list (LEFT pane) renders via x-for over `files`.
  - Editor (RIGHT pane) has a textarea + live preview pane bound to
    `content` and `preview`.
  - Toolbar wires Save / Undo / Redo buttons + the diff dropdown.
  - Diff panel renders sanitised HTML via x-html when a revision is
    selected.
  - The factory exposes the load / select / renderPreview / save /
    undo / redo / loadDiff / newFile contract used by the tests
    against test_memories_editor.py (the API tests are unchanged).

Mirrors the test_v19_project_tabs.py pattern — pure template-source
assertions, no live server. Behavioural integration is covered by
the manual screenshot verification step on the sprint orchestrator.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
    / "project_detail.html"
)


def _read() -> str:
    return TEMPLATE_PATH.read_text()


def test_a2_placeholder_banner_removed() -> None:
    """The v19.a2 stop-gap banner — operator's "v10 over-reported memories
    editor" gripe was about that placeholder lingering. v19.0.0a6 ships
    the real editor, so the banner must be gone."""
    src = _read()
    assert "Memories editor — full implementation lands in v19.0.0a6." not in src, (
        "v19.a2 placeholder banner should have been replaced by the new editor"
    )


def test_legacy_memories_panel_block_is_inert() -> None:
    """The legacy memoriesPanel viewer + 535-line factory still lives in
    the file (kept as an artefact for one release for diff-friendliness),
    but it MUST be wrapped in `{% if false %}` so Jinja never emits it.
    Removing the wrapper without first deleting the block would re-mount
    a second Alpine component on the same page."""
    src = _read()
    # Wrapper is present and on its own line (not part of some unrelated
    # macro).
    assert "{% if false %}" in src, "legacy block must be wrapped in {% if false %}"
    # The legacy factory still exists inside the wrapper.
    assert "function memoriesPanel(initial) {" in src
    # The marker we attached when wrapping is present.
    assert 'data-legacy-removed="memoriesPanel-v15"' in src
    # The {% if false %} wrapper opens BEFORE the legacy block and the
    # matching {% endif %} closes AFTER it.
    if_idx = src.index("{% if false %}")
    # Anchor on the indented form so we don't pick up the prose mention
    # in the wrapper comment (which appears at column 0).
    legacy_factory_idx = src.index("  function memoriesPanel(initial) {")
    endif_idx = src.index("{% endif %}", legacy_factory_idx)
    assert if_idx < legacy_factory_idx < endif_idx


def test_memories_tab_mounts_new_editor_factory() -> None:
    """The Memories tab section binds the new `memoriesEditor` factory
    via x-data + x-init, scoped to the current project name."""
    src = _read()
    # The tab section uses the new factory, with project_name as the
    # constructor arg.
    assert 'x-data="memoriesEditor({{ project_name | tojson }})"' in src
    assert 'x-init="loadFiles()"' in src
    # And only one Memories panel exists at runtime (the legacy one is
    # inside `{% if false %}`, which is detected separately above).
    # The tab's x-show guard remains intact.
    assert "x-show=\"active === 'memories'\"" in src


def test_file_list_pane_renders() -> None:
    """LEFT pane renders the files array, with an empty-state message
    that preserves the v10.0.0a5 `data-empty-state` selector so existing
    e2e empty-state assertions still pass."""
    src = _read()
    # x-for over files in the new editor (different key prefix than the
    # legacy panel, which used 'mem:').
    assert "x-for=\"file in files\"" in src
    assert "'memfile:' + file.name" in src
    # New-file button.
    assert '@click="newFile()"' in src
    # Empty-state marker carries forward (operator dashboards filter on
    # this attribute).
    assert 'data-empty-state="memories.no-files"' in src


def test_editor_pane_has_split_textarea_and_preview() -> None:
    """RIGHT pane: textarea bound to `content` (with debounced
    onContentChange + Cmd/Ctrl+Z handlers), live preview bound to
    `preview` via x-html. Both panes co-exist in a 2-col grid."""
    src = _read()
    # Textarea wiring.
    assert 'x-model="content"' in src
    assert "@input.debounce.300ms=\"onContentChange()\"" in src
    # Cmd/Ctrl+Z wired for undo/redo (modifier key matters for desktop
    # operator muscle-memory).
    assert "@keydown.meta.z.prevent=\"undo()\"" in src
    assert "@keydown.ctrl.z.prevent=\"undo()\"" in src
    assert "@keydown.meta.shift.z.prevent=\"redo()\"" in src
    # Live preview pane.
    assert 'x-html="preview"' in src
    assert "Live markdown preview" in src


def test_toolbar_has_save_undo_redo_diff_controls() -> None:
    """Toolbar exposes Save / Undo / Redo buttons + a diff-against-
    revision dropdown. Save is gated on `dirty`; Undo/Redo on the
    canUndo/canRedo computed flags. The diff dropdown lists revisions
    keyed by id and triggers loadDiff() on change."""
    src = _read()
    # Save button + dirty gate.
    assert '@click="save()"' in src
    assert ':disabled="!dirty || saving"' in src
    # Undo/redo buttons.
    assert '@click="undo()"' in src
    assert '@click="redo()"' in src
    assert ':disabled="!canUndo()"' in src
    assert ':disabled="!canRedo()"' in src
    # Diff dropdown.
    assert 'x-model="diffAgainst"' in src
    assert '@change="loadDiff()"' in src
    # Each option carries the revision id as its value.
    assert "x-for=\"r in revisions\"" in src


def test_diff_panel_renders_sanitised_html() -> None:
    """When a revision is selected (`diffAgainst` truthy), a panel
    renders the server-returned HTML diff via x-html."""
    src = _read()
    assert 'x-show="diffAgainst"' in src
    assert 'x-html="diffHtml"' in src


def test_memories_editor_factory_exposes_required_methods() -> None:
    """The Alpine factory must expose the loadFiles / select /
    renderPreview / save / undo / redo / loadDiff / newFile contract.
    The screenshot pass + the existing memories API tests both depend
    on these names."""
    src = _read()
    # Factory definition.
    assert "function memoriesEditor(projectName) {" in src
    # Core methods.
    for method in (
        "loadFiles",
        "select",
        "loadRevisions",
        "renderPreview",
        "save",
        "undo",
        "redo",
        "canUndo",
        "canRedo",
        "loadDiff",
        "newFile",
        "formatSize",
        "onContentChange",
    ):
        assert (
            f"{method}(" in src
        ), f"memoriesEditor must expose {method!r}"


def test_render_markdown_post_uses_text_field() -> None:
    """The /api/render-markdown endpoint accepts {text: ..., project: ...}
    (NOT {content: ...} — that's the PUT /memories body shape). Mixing
    them up was the bug pattern that killed the v11 preview iteration."""
    src = _read()
    # The renderPreview() body must use `text:`.
    assert "JSON.stringify({ text: this.content, project: this.project })" in src
    # The save() body must use `content:`.
    assert "JSON.stringify({ content: this.content })" in src


def test_memory_history_endpoint_uses_query_string() -> None:
    """memory-history is a query-string API (?file=…), NOT a path-
    embedded one. Path-embedded would collide with the catch-all
    `{file_token:path}` route on the memory viewer."""
    src = _read()
    assert "/memory-history`" in src
    assert "`?file=${encodeURIComponent(this.active.name)}`" in src


def test_diff_endpoint_requests_html_format() -> None:
    """loadDiff() asks the server for `format=html` so we can drop the
    sanitised HtmlDiff table into the diff panel via x-html. Unified
    text would render as escaped source inside x-html."""
    src = _read()
    assert "/memory-revisions/diff`" in src
    assert "`&format=html`" in src


def test_memories_editor_section_has_role_tabpanel() -> None:
    """The Memories tab section keeps role='tabpanel' so the projectTabs
    accessibility contract (asserted in test_v19_project_tabs.py) holds.
    A regression here would make all 5 panels stop counting as tabpanels."""
    src = _read()
    # Target the new editor section specifically — it's the only Memories
    # tab section now (the legacy one is inside `{% if false %}`).
    assert (
        'aria-label="Memories"\n           x-data="memoriesEditor'
        in src
    )
