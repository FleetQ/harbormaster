"""LLM-based triple extraction (v2.0.0a5).

Replaces the regex heuristics in `triples.py` with a one-shot prompt
to the configured backend. The prompt asks the LLM to return a JSON
array of `(subject, predicate, object, confidence)` records extracted
from the answer text. We parse that array back into `Triple`s and
hand them to `KGWriter` like any other writeback.

Cost discipline:
- One `ask_local()` call per ask_project / delegate_task — doubles the
  per-tool cost when enabled. Operators opt in via
  `[fleetq] kg_extractor = "llm"` (default heuristic, free).
- `max_triples` caps the output size.
- We do NOT recurse: the extracted triples are not themselves
  re-extracted. One pass per answer.

Failure modes:
- Backend errors → empty list (caller falls through to heuristic if
  configured for "both", or skips KG writeback for "llm").
- JSON parse failures → empty list, logged at WARNING.
- Model returns malformed records → those records are dropped, the
  rest are kept. Per-record validation.

Local-only: this extractor needs a backend `ask_local()` against a
project cwd. Cross-host extraction would require an SSH round trip
per call, which is too expensive to justify in v2.0.0a5. The dispatch
layer in `_helpers.py` honours that by falling through to heuristic
extraction for remote `host` arguments.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from harbormaster.backends.base import Backend, BackendError
from harbormaster.fleetq.kg import Triple

logger = logging.getLogger("harbormaster.fleetq.triples_llm")


_PROMPT_TEMPLATE = """\
You are a knowledge-graph extractor.

Extract structured (subject, predicate, object) triples from the
ANSWER text below. The triples should describe relationships
involving the source project ({source_project!r}) — what it mentions,
uses, exposes, depends on, integrates with, etc.

Return ONLY a JSON array. Each element is an object with keys:
  - "subject"    : string (usually {source_project!r})
  - "predicate"  : short verb / noun like "mentions", "uses",
                   "exposes", "depends_on", "integrates_with"
  - "object"     : string (the target entity name, library, endpoint,
                   service, file path — whatever fits the predicate)
  - "confidence" : number between 0.0 and 1.0

Limit your output to AT MOST {max_triples} triples. Skip vague /
filler statements. Prefer concrete entity names over paraphrases.

Output JSON only — no markdown fences, no prose, no preface.

ANSWER TEXT:
---
{answer}
---
"""


def _build_extraction_prompt(
    *, answer: str, source_project: str, max_triples: int
) -> str:
    return _PROMPT_TEMPLATE.format(
        answer=answer.strip(),
        source_project=source_project,
        max_triples=max_triples,
    )


def _strip_markdown_fence(text: str) -> str:
    """Tolerate ```json …``` or ``` …``` fences around the JSON
    payload — some models add fences even when the prompt says no."""
    s = text.strip()
    if s.startswith("```"):
        # Drop opening fence (with optional language tag) and matching
        # closing ```.
        first_newline = s.find("\n")
        if first_newline > 0:
            s = s[first_newline + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _extract_array(text: str) -> str | None:
    """Locate the first JSON array in `text`, scanning past any leading
    prose. Returns the array slice, or None when no `[` is found."""
    text = _strip_markdown_fence(text)
    start = text.find("[")
    if start == -1:
        return None
    # Find the matching closing bracket by counting depth.
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_triples(
    *,
    text: str,
    source_project: str,
    max_triples: int,
) -> list[Triple]:
    """Parse the LLM response into `Triple`s. Drops malformed records
    silently; a single bad record must not poison the whole batch."""
    array_text = _extract_array(text)
    if array_text is None:
        logger.warning(
            "llm-triples: response contained no JSON array; %d chars",
            len(text),
        )
        return []
    try:
        parsed = json.loads(array_text)
    except json.JSONDecodeError as e:
        logger.warning("llm-triples: JSON parse failed: %s", e)
        return []
    if not isinstance(parsed, list):
        logger.warning(
            "llm-triples: top-level value is %s, expected list",
            type(parsed).__name__,
        )
        return []

    out: list[Triple] = []
    for raw in parsed[:max_triples]:
        if not isinstance(raw, dict):
            continue
        subject = raw.get("subject") or source_project
        predicate = raw.get("predicate")
        # Tolerate either "object" (canonical wire shape) or "obj"
        # (some models autofill the dataclass field name).
        obj = raw.get("object", raw.get("obj"))
        confidence = raw.get("confidence")
        if not isinstance(predicate, str) or not predicate.strip():
            continue
        if not isinstance(obj, str) or not obj.strip():
            continue
        try:
            conf = float(confidence) if confidence is not None else 0.7
        except (TypeError, ValueError):
            conf = 0.7
        conf = max(0.0, min(1.0, conf))
        out.append(
            Triple(
                subject=str(subject),
                predicate=predicate.strip(),
                obj=obj.strip(),
                confidence=conf,
            )
        )
    return out


def extract_via_llm(
    *,
    answer: str,
    source_project: str,
    backend: Backend,
    cwd: Path,
    max_triples: int = 20,
) -> list[Triple]:
    """One-shot LLM extraction. Returns the parsed triple list (capped
    at `max_triples`), or an empty list on backend / parse failure.

    Local-only: callers MUST resolve `cwd` to the project's local path
    before invoking. Remote / SSH-only projects should fall through to
    `triples.extract_all()` instead — the LLM call's overhead is too
    high to justify per-host SSH execution.
    """
    if not answer or len(answer.strip()) < 8:
        return []

    prompt = _build_extraction_prompt(
        answer=answer, source_project=source_project, max_triples=max_triples
    )
    try:
        result = backend.ask_local(cwd=cwd, prompt=prompt, max_turns=1)
    except BackendError as e:
        logger.warning("llm-triples: backend call failed: %s", e)
        return []
    return _parse_triples(
        text=result.output,
        source_project=source_project,
        max_triples=max_triples,
    )
