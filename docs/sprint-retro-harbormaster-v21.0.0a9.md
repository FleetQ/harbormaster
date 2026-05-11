# Sprint retro — harbormaster v21.0.0a9

**Phase 9 of 10 in the v21.0.0 alpha series.**
Long-deferred UI cluster: replace the static Mermaid project-deps graph
with the same Cytoscape force-directed renderer already vendored for
``/network`` (v10.0.0a7), and extend ``ProjectInfo.language`` (v6.0.0a3)
with a linguist-style file-extension fallback. Both items were
explicitly held over from v7-era retros pending a "real reason" — the
Cytoscape vendor landing in v10 + the multiprocess discovery work in
v21.0.0a8 surfacing more projects with ``language="unknown"`` finally
made now the time.

## What shipped

### Part A — Cytoscape project-deps graph (default renderer)

The dashboard ``Project graph`` card now renders via Cytoscape using the
existing ``/static/vendor/cytoscape.min.js`` bundle (vendored in
v10.0.0a7 for the inter-project ``/network`` view). The legacy Mermaid
``<pre class="mermaid">`` block is kept behind a "use Mermaid" toggle.

* ``/api/graph?format=cytoscape`` adds a ``cytoscape`` field to the
  existing response (``{nodes:[{data:{id,label,language}}], edges:
  [{data:{id,source,target,kind}}]}``) alongside the legacy ``mermaid``
  markup. Both shapes ship in one round-trip so the dashboard can
  switch renderer without re-fetching. Default behaviour
  (no ``format`` param) is unchanged — only ``mermaid`` is emitted, so
  any external consumer continues to work.
* ``_graph_to_cytoscape(graph)`` is the shape adapter — pure function of
  ``ProjectGraph``, lives at module scope in ``ui/routes.py`` next to
  ``McpProxyRequest``.
* ``dashboard.html`` ``graphPanel()`` Alpine scope now carries a
  ``renderer`` field (``'cytoscape'`` default, ``'mermaid'`` fallback)
  persisted to ``localStorage['hm:graph:renderer']``. ``init()``
  restores the operator's last toggle on every page load.
* Node colours follow the v6.0.0a3 sidebar palette — python=blue,
  javascript=yellow, typescript=cyan, php=purple, rust=orange, go=teal,
  ruby=red, java=brown. Edge ``kind`` styles match the Mermaid arrow
  semantics: solid (``dep``), dashed (``dev_dep``), teal
  (``transitive``).
* Click a node → ``window.location = '/projects/<name>'``. The graph
  is now a navigation surface, not just a viz.
* Layout: ``cose`` (force-directed), ``idealEdgeLength: 80``,
  ``fit: true``, ``padding: 12``, ``animate: false`` for deterministic
  rendering.

### Part B — linguist-style language detection fallback

``projects.py::_detect_language`` previously returned ``"unknown"``
when no manifest matched. v21.0.0a9 adds a final fallback that samples
file extensions linguist-style.

* New ``_detect_language_from_extensions(project_path, max_files=200)``
  — walks ``rglob("*")``, counts known extensions, returns the
  majority language; ``None`` when no recognised source file is
  present.
* Skips hidden dirs (any path part starting with ``.``: ``.git``,
  ``.venv``, ``.serena``, ``.pytest_cache``, etc.) plus
  ``node_modules`` / ``vendor`` / ``__pycache__`` / ``dist`` /
  ``build``.
* ``max_files`` cap is "files that *count*" — files outside the
  recognised extension set don't burn the budget. A docs-only mega-
  repo still pays the walk but returns fast.
* Tie-break is alphabetical so the result is deterministic across
  runs.
* Extension table is module-level (``_EXT_TO_LANG``) so future
  additions land in one place. Markdown / txt are explicitly mapped
  to ``None`` so docs don't pretend to be code.

### Tests + safety nets

* 12 new tests in ``tests/unit/test_ui.py``:
  * 4 covering ``/api/graph?format=cytoscape`` — default omits the
    new field, presence + shape under the flag, node ids match
    project names.
  * 7 covering ``_detect_language_from_extensions`` — python-only,
    majority TypeScript, docs-only → None, hidden-dirs ignored,
    dependency-dirs ignored, ``max_files`` cap, end-to-end
    fall-through.
  * 1 keeping the existing ``_detect_language`` contract (rust
    detected via extension when no Cargo.toml present).
* ``tests/ui/test_template_safety.py``: the ``!graphLoading``
  allowlist entry was widened to ``renderer === 'mermaid' &&
  !graphLoading`` (the same JS pre-flip guarantee holds — see code
  comment); the sanity scanner check loosened to substring match.

## How it shipped

Branch ``feat/v21.0-cytoscape-and-linguist`` → PR → merge --no-ff →
version bump → tag → PyPI verify. No CI gating issue — the
pre-existing ``test_bridge.py`` fixture-scope collision and the
SSE/streaming module-state cross-talk in
``tests/ui/test_typed_sse_events.py``+``test_streaming_qa_writeback.py``
both pre-date v21.0.0a9 (verified by stashing the branch and re-running
at HEAD: 36 failures at baseline). New tests pass cleanly in
isolation and inside the full sweep.

Visual verification: full-page screenshot via Playwright at
``http://127.0.0.1:17799/`` confirmed Cytoscape canvas (3 layers,
798×280) renders with cose-laid-out nodes coloured by language.
``/tmp/v21-a9-graph-only.png`` shows the new view — purple plugins
cluster around the agent-fleet-cloud hub, with yellow/blue/orange
islands for tailwind/harbormaster-mcp/etc.

## Notes for Phase 10

* Phase 10 = MODEL SELECTION. No follow-up debt from Phase 9 — the
  Mermaid fallback toggle gives every operator a back-out path if
  Cytoscape ever misbehaves on a specific node set.
* The linguist fallback is intentionally conservative (200-file cap +
  hidden-dir skip). If a heavy monorepo with no manifest ever
  surfaces, raise the cap in one place via the function default.
* Click-node-to-project nav is a free invariant from the canonical
  node id = project name mapping. If a future renamer breaks that
  invariant, the existing ``validate_project_name`` regex will reject
  the navigation at ``/projects/<bad>`` and the operator sees a 400.
