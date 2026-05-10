# Harbormaster v10.0.0a8 — Sprint Retro

**Phase 8 of 8** in the v10.0 alpha chain.

## Shipped

**Network chat-view + view-toggle persistence.**

Adds a chronological event-log alternate to v10.0.0a7's
`/network` graph view. The header view-toggle now persists the
operator's last choice in localStorage, so a reload returns to the
preferred surface.

## Implementation

Template (`templates/network.html`):
- New `<ul id="hm-network-chat">` block — rendered when
  `view === 'chat'`. One row per event:
  `[time] caller → tool(target) "<truncated question>"`
- Each row is collapsible (Alpine `{open:false}`) and reveals
  the full 200-char preview on click.
- Tool-color spans match the graph-view edge palette.
- New `chatOrder()` Alpine method returns events in reverse so
  the newest activity sits at the top — matches operator
  expectations for an event log.
- The header view-toggle (already wired in v10.0.0a7) now
  persists to `localStorage.setItem('hm:network:view',
  'graph'|'chat')`. `init()` restores the saved view on mount.
- Toggling back to graph triggers a `requestAnimationFrame`
  re-render so Cytoscape re-fits when the container becomes
  visible again.

## Tests (7)

`tests/ui/test_network_chat_view.py`:
- Template includes the chat-view block + chatOrder hook.
- Row format renders caller / tool / target columns.
- Rows collapsible with full-preview reveal on click.
- localStorage key `hm:network:view` set + get hooked.
- View-toggle dispatches both 'graph' and 'chat' events.
- chatOrder returns reverse-sorted events.
- /network end-to-end smoke (still serves; both view ids present).

## Numbers

- Tests: 1090 → 1097 (+7).
- Source files: 53 → 53 (template-only change + tests).
- mypy --strict: clean.
- ruff: clean.

## Deviations

None.

## Risks / Follow-ups

- The chat view truncates each preview to 80 chars on the row
  and reveals the full 200 chars on expand. The 200-char ceiling
  comes from the ring buffer (server-side hard truncate). If
  operators want longer previews on the chat surface, raise the
  ring-buffer cap — beware memory cost (500 events * cap).
- `chatOrder()` reverses the events array on every render. For
  500 events that's negligible; if the buffer grows past a few
  thousand we should switch to `array.prototype.reverse()` once
  on insert and maintain a `_reverse` cache.
- Phase 8 is the last alpha; v10.0.0 GA follows with a cumulative
  retro spanning all 8 alphas.
