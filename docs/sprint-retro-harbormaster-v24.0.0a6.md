# Sprint Retro — Harbormaster v24.0.0a6

**Date:** 2026-05-13
**Theme:** Second template split. The Q&A History + Settings tabs
(228 lines of `<section>` + Alpine factories) move from
`project_detail.html` into `_partials/_project_detail_qa_and_settings.html`.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/templates/_partials/_project_detail_qa_and_settings.html` | new — 228 LOC, Q&A history tab + settings tab + their Alpine factories |
| `src/harbormaster/ui/templates/project_detail.html` | inline block replaced by `{% include %}` |
| 8 test files in `tests/ui/` | upgraded `_expand_includes` helper to KEEP include directive AND APPEND partial content (so grep tests pass either way) |
| `src/harbormaster/__init__.py` | 24.0.0a5 → 24.0.0a6 |

## Numbers

- 10+ files (1 new partial, project_detail.html, 8 test files,
  __init__.py).
- `project_detail.html`: **1964 → 1737 LOC (-227, -11.6%)**. First
  measurable reduction since v19.
- 2030 → 2037 tests (+7 — same fixture-split pattern as v24.0.0a5).
  mypy --strict clean. ruff clean.

## Design notes

### Incident #1: block-boundary mismatch

First extraction attempt grabbed lines 1570–1963, which crossed the
`{% endblock %}` of `content` (line 1799) into a separate
`{% block inspector %}` block. Result: partial contained a stray
`{% endblock %}` that Jinja rejected with
`Encountered unknown tag 'endblock'`.

**Fix**: search for the FIRST `{% endblock %}` after the section
start (not the last). The block-boundary check is essential when
extracting from templates that use multi-block inheritance
(Jinja `{% block X %}` ... `{% endblock %}`).

### Incident #2: helper semantics — replace vs append

First `_expand_includes` REPLACED the `{% include "..." %}` directive
with the partial's content. That broke tests asserting
`'{% include "_partials/X.html" %}' in src`. The v24.0.0a6 final
shape KEEPS the include line AND appends the partial's content right
after, so both kinds of grep pass:

```python
def _expand_includes(content: str, base) -> str:
    pat = re.compile(r'(\{%\s*include\s+"(_partials/[^"]+)"\s*%\})')
    def _sub(m):
        return m.group(1) + "\n" + (base / m.group(2)).read_text(...)
    return pat.sub(_sub, content)
```

8 test files patched with this final helper.

### Block-boundary search heuristic

The first-`{% endblock %}`-after-start rule works for this codebase
because project_detail.html has two cleanly-separated blocks. Future
template splits using `{% include %}` partials should verify with
`grep -n "block \|endblock" template.html` before deciding the
extraction range.

## Carry-over

- v24.0.0a7: FleetQ Bridge completion-webhook subscriber (Tier 3
  close-out; FleetQ side delivered)
- v24.0.0 GA

After v24.0.0a6, `project_detail.html` is at ~1737 LOC. Remaining
big-file debt across templates:
- `project_detail.html`: ~1737 (down from 1964)
- `dashboard.html`: 2787 (down from 3064)
- `network.html`: ~1030 (unchanged)

The remaining splits are tractable extensions of the v24.0.0a5/a6
pattern (find self-contained x-data scope, mind the block boundaries,
use `_expand_includes` in tests).

## Operator-facing note

After upgrading to v24.0.0a6:

- **No behaviour changes.** The Q&A History and Settings tabs on
  `/projects/{name}` render identically; their endpoints
  (`/api/recall`, `/api/projects/{name}/budget`) are unchanged.
- Source readers: project Q&A history + settings UI lives in
  `_partials/_project_detail_qa_and_settings.html`. The Jinja
  `{% include %}` happens just before the content block's closing
  `{% endblock %}`.
- Source-grep test pattern (`_expand_includes`) is now in 8 test
  files. Future template splits can copy any of them as a template;
  the helper keeps include lines AND appends partial content.
