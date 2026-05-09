"""Heuristic triple extraction from claude -p answer text.

No LLM call — pure regex / keyword matching. Three predicates ship in
v1.2 phase 2:

  * project—mentions—project   (cheapest; matches known project names
                                in the answer text)
  * project—uses—library       (matches "uses the X library" / "depends on X")
  * project—exposes—endpoint   (matches "GET /api/foo" / "POST /v1/...")

All extractors are best-effort and tagged with a confidence score
that the FleetQ side (or downstream consumers) can use to filter.

Why heuristic, not LLM-based: the cost-per-call must be near-zero so
this can run on every successful tool invocation. An LLM call would
double our `claude -p` spend per ask_project. The triples are noisy
but durable — better than nothing, and a future v2 LLM-extraction
phase can re-process the trajectory text post-hoc.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from harbormaster.fleetq.kg import Triple

# project—mentions—project
# Matches a known project name appearing as a whole token. Tokens
# include the hyphen since project names like `agent-fleet-cloud` and
# `harbormaster-mcp` are common in this ecosystem; tokenising on
# whitespace+punctuation-but-not-hyphen keeps multi-segment names whole.
_WORD_BOUNDARY = re.compile(r"[A-Za-z0-9_-]+")


def extract_project_mentions(
    *,
    answer: str,
    source_project: str,
    known_projects: Iterable[str],
) -> list[Triple]:
    """Return one mentions-triple per known project name that appears
    in the answer text (deduped, excludes the source project itself)."""
    tokens = {t.lower() for t in _WORD_BOUNDARY.findall(answer)}
    out: list[Triple] = []
    seen: set[str] = set()
    for name in known_projects:
        if name == source_project or name in seen:
            continue
        # Match by lowercase token; also try the bare composer-style suffix.
        candidates = {name.lower()}
        if "/" in name:
            candidates.add(name.split("/", 1)[1].lower())
        if candidates & tokens:
            out.append(
                Triple(
                    subject=source_project,
                    predicate="mentions",
                    obj=name,
                    confidence=0.6,  # heuristic — false positives possible
                )
            )
            seen.add(name)
    return out


# project—uses—library
# Patterns: "uses the X library", "uses X", "depends on X", "requires X"
# We anchor on phrasing that signals a deliberate dep statement, not
# just any mention. Library name is a sequence of valid package chars.
_LIB_NAME = r"[A-Za-z0-9._/-]+"
_USES_PATTERNS = (
    re.compile(rf"\buses?\s+the\s+(?P<lib>{_LIB_NAME})\s+library\b", re.IGNORECASE),
    re.compile(rf"\bdepends?\s+on\s+(?P<lib>{_LIB_NAME})\b", re.IGNORECASE),
    re.compile(rf"\brequires?\s+(?P<lib>{_LIB_NAME})\b", re.IGNORECASE),
    re.compile(rf"\bbuilt\s+on\s+(?P<lib>{_LIB_NAME})\b", re.IGNORECASE),
)


def extract_uses(
    *, answer: str, source_project: str
) -> list[Triple]:
    """Extract 'X uses Y' triples from sentence patterns."""
    out: list[Triple] = []
    seen: set[str] = set()
    for pattern in _USES_PATTERNS:
        for match in pattern.finditer(answer):
            lib = match.group("lib").rstrip(".,;:)")
            if not lib or lib.lower() in seen:
                continue
            seen.add(lib.lower())
            out.append(
                Triple(
                    subject=source_project,
                    predicate="uses",
                    obj=lib,
                    confidence=0.55,
                )
            )
    return out


# project—exposes—endpoint
# Matches HTTP-method-prefixed paths: "GET /api/foo", "POST /v1/bar".
# Confined to /-prefixed paths so we don't grab arbitrary tokens.
_ENDPOINT_PATTERN = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+"
    r"(?P<path>/[A-Za-z0-9._/{}\-]+)"
)


def extract_endpoints(
    *, answer: str, source_project: str
) -> list[Triple]:
    """Extract 'X exposes endpoint' triples."""
    out: list[Triple] = []
    seen: set[str] = set()
    for match in _ENDPOINT_PATTERN.finditer(answer):
        method = match.group("method").upper()
        path = match.group("path").rstrip(".,;:)")
        endpoint = f"{method} {path}"
        if endpoint in seen:
            continue
        seen.add(endpoint)
        out.append(
            Triple(
                subject=source_project,
                predicate="exposes",
                obj=endpoint,
                confidence=0.7,  # high — pattern is anchored to HTTP verbs
            )
        )
    return out


def extract_all(
    *,
    answer: str,
    source_project: str,
    known_projects: Iterable[str],
    max_triples: int = 50,
) -> list[Triple]:
    """Run every extractor and return the combined set, capped at
    `max_triples` to bound the per-call writeback cost. Order: mentions
    first (cheapest), then uses, then endpoints — so the cap drops
    higher-noise triples first when the answer is dense."""
    triples: list[Triple] = []
    triples.extend(extract_project_mentions(
        answer=answer,
        source_project=source_project,
        known_projects=known_projects,
    ))
    triples.extend(extract_uses(answer=answer, source_project=source_project))
    triples.extend(extract_endpoints(answer=answer, source_project=source_project))
    return triples[:max_triples]
