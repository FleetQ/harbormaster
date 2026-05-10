# Sprint Retro — Harbormaster v13.0.0a6

**Theme:** Operator-facing config doc consolidation. Closes
v12 retro #3 ("config docs scattered across READMEs, design docs,
and per-feature retros").

## What shipped

### `docs/operator-config-reference.md`

A single canonical reference for every TOML config section. ~370
lines covering:

- **Loading order** — search path + zero-config fallback + strict
  validation behaviour
- **Table of contents** with anchor links to every section
- **Per-section tables** for: `[projects]`, `[ignore]`,
  `[backends.<name>]`, `[hosts.<label>]`, `[server]`,
  `[storage]`, `[fleetq]`, `[history]`, `[plugins]`,
  `[retention]`, plus **top-level keys** (`default_backend`,
  `backends_for_project`)
- Each section: type / default / valid range for every key,
  plus a runnable TOML example
- **Worked example** at the end — full multi-section TOML showing
  two backends, two hosts, FleetQ writeback with KG triples,
  parallel dispatcher, history with auto-grounding, plugin
  allowlist, bumped retention caps

### `README.md` link

Replaces the previous pointer to
`docs/architecture-harbormaster.md §3` (which had drifted) with
a direct link to the new canonical reference.

### `tests/unit/test_config_doc_reference.py` — 6 regression tests

Acts as an active doc-coverage gate so future PRs adding config
fields don't silently miss documentation:

- `test_doc_exists_and_nonempty` — file present, > 1KB
- `test_readme_links_to_doc` — README points at the canonical
  reference
- `test_every_documented_section_in_worked_example` — every
  `## \`[<section>]\`` header has a corresponding `[…]` block in
  the worked-example TOML (catches sections described in prose
  but missing from the example). Handles `<name>` / `<label>`
  placeholders by checking the prefix
- `test_every_config_field_documented` — walks every Pydantic
  field on `HarbormasterConfig` (recursively into sub-models)
  and asserts each field name appears at least once in the
  reference. **Direct coverage gate against undocumented config
  keys** — adding a new field to `config.py` without updating
  the doc fails this test
- `test_doc_has_table_of_contents` — operators jump straight to
  what they need
- `test_doc_has_loading_order_section` — file-search path is
  the first thing operators ask; must be documented up front

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1359 passed, 3 skipped in 39.9s
```

Test count delta: 1353 → 1359 (+6).

## Patterns proven this sprint

### Doc-link smoke as a coverage gate

`test_every_config_field_documented` is a 30-line piece of
reflection that turns the entire Pydantic config model into a
documentation contract. Adding a new field to `config.py`
fails the test until the doc is updated — same lockstep
discipline as the v13.0.0a2 template-migration regression test.

### Single canonical reference

The doc deliberately replaces, rather than augments, the prior
scattered references. Operators looking for a config knob now
have exactly one place to check. Future feature retros can
focus on what shipped + why; the persistent reference holds the
"and here's the new key" details.

## Quality of life

- New operators: zero scavenger-hunt to find every `[section]` —
  one file lists them all with examples.
- Future contributors: `pytest tests/unit/test_config_doc_reference.py`
  passes/fails immediately on doc drift; no manual cross-checking.
- README pointer is now stable — it indexes one reference instead
  of a section number that can drift as the architecture doc
  evolves.
