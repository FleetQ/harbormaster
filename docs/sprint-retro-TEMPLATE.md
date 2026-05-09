# Sprint Retro — Harbormaster v<X.Y.Z>

**Date:** YYYY-MM-DD
**Theme:** One-line summary of what this sprint optimised for.
Distinguish "shipped a feature" from "paid down debt" from "polish
existing surface" — future-you reading the retro list at a glance
needs to see the shape of the sprint without reading the body.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `<short-sha>` | first commit subject (#PR) |
| `<short-sha>` | second commit subject (#PR) |

### `agent-fleet` (community-edition base submodule)

| SHA | Subject |
|-----|---------|
| `<short-sha>` | first commit subject (#PR) |

> Drop the agent-fleet table when no cross-repo work shipped. Drop
> the harbormaster table only if the entire sprint was cross-repo —
> typically there's at least one harbormaster commit even on a
> "fix the FleetQ side" sprint (the cross-repo coordination usually
> generates a doc / smoke / changelog change here too).

## Capabilities (this sprint)

> One subsection per shipped action item. Number them to match the
> previous retro's "Action items for the next sprint" so reviewers
> can grep for "did item N actually ship" cleanly. If an item didn't
> ship, list it under "Out-of-scope (still)" below — don't silently
> drop it.

### 1 · `<one-line summary>`

What changed in 2-4 sentences. Lead with the user-facing effect,
not the implementation. Implementation details only if the
mechanism is non-obvious or load-bearing for future work.

If there's a wire shape (HTTP API, SSE event, MCP envelope), spell
it out with a code block — wire shapes are the highest-leverage
thing to capture, because they're hardest to reconstruct from git
log later.

### 2 · `<one-line summary>`

…

## Real numbers

- N/M previous-sprint retro action items shipped
- K PRs opened / merged (cross-repo split if applicable)
- New unit tests + new feature/integration tests
- Test suite delta: <before> → <after> passed
- Lint / type-check status
- Backwards-incompatible changes (target: 0)

> The point of this section is "five sprints from now, can you tell
> at a glance whether this was a heavy or light sprint." Numbers
> beat adjectives.

## What worked

> Things to keep doing. Bullet each one with the *mechanism* —
> "PR-per-action-item" is a mechanism; "good teamwork" isn't. If
> a particular technique gave outsized leverage, name it so it
> ends up in the team's muscle memory.

- **<technique>.** What it actually did for you this sprint.
- **<technique>.** …

## What to change / next

> Friction points, near-misses, stuff that almost shipped but
> didn't. These become input for the next sprint's action items
> AND for what to flag in the next "What worked" / "What to change"
> section. Be specific — vague "communication issues" entries are
> useless six weeks later. "The CI smoke job was gated behind a
> repo variable that nobody had set, so we didn't notice the
> regression for 24 hours" is actionable.

- **<thing>.** What broke or felt wrong, what would you do about it.
- **<thing>.** …

## Action items for the next sprint (v<NEXT> / week <N+1>)

> 4-6 items, each shippable inside one sprint. Number them so the
> next retro can match "did N ship" without ambiguity. Each item:
> imperative phrasing ("Implement X" not "X needs implementing"),
> specific scope, no "investigate" / "explore" verbs (those are
> not shippable).

1. **<imperative title>.** One paragraph of context — what's the
   pain, where does the code live, what's the deliverable.
2. **<imperative title>.** …

## Out-of-scope (still)

> The "deferred forever-ish" list. Keep this stable across sprints
> (only edit when something genuinely moves in scope). Acts as
> a contract with reviewers — "yes, we know this exists, no we're
> not doing it now."

- <item> — <one-line reason>.
- <item> — <one-line reason>.

---

## Authoring notes (delete before publishing)

- File name: `docs/sprint-retro-harbormaster-v<X.Y.Z>.md`. Keep the
  same prefix — they're listed and grepped together.
- Length: 200-400 lines. Five sprints in, that's the sweet spot
  between "scannable" and "captures enough context."
- Tense: past tense for "What landed" / "Capabilities", present
  tense for "What worked" / "What to change", imperative for
  "Action items".
- Cross-references: link to the matching PR(s) in agent-fleet /
  harbormaster — sprint retros are the only place that ties them
  together for non-team readers.
- Before publishing: remove this "Authoring notes" section, all
  the `>` blockquote guidance, and any `<placeholder>` literals.
- After publishing: bump the README "Status" section, tag the
  release, push the tag (publish workflow handles PyPI).
