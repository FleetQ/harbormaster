"""Tests for LLM-based triple extraction (v2.0.0a5).

Mocks the backend so tests don't actually spawn claude/codex. Exercises:
- prompt construction
- happy-path JSON parsing
- markdown-fence tolerance
- prefix-prose tolerance (LLM emits "Sure, here you go: [...]")
- malformed records dropped, the rest kept
- top-level non-array → empty
- backend error → empty
- short / empty answer → empty without invoking backend
- max_triples cap honoured
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.fleetq.triples_llm import (
    _build_extraction_prompt,
    _extract_array,
    _parse_triples,
    _strip_markdown_fence,
    extract_via_llm,
)


@dataclass
class FakeBackend:
    name: str = "fake"
    cfg: Any = None
    response: str = "[]"
    raises: BackendError | None = None
    last_prompt: str | None = None

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int) -> BackendResult:
        self.last_prompt = prompt
        if self.raises is not None:
            raise self.raises
        return BackendResult(output=self.response, duration_ms=1)

    def ask_remote(self, **_kwargs: Any) -> BackendResult:  # pragma: no cover
        raise AssertionError("ask_remote should not be called by extract_via_llm")


# --- prompt construction --------------------------------------------------


def test_prompt_contains_source_project_and_answer():
    prompt = _build_extraction_prompt(
        answer="My answer.", source_project="my-app", max_triples=15
    )
    assert "'my-app'" in prompt
    assert "My answer." in prompt
    assert "15" in prompt


# --- markdown / array extraction -----------------------------------------


def test_strip_markdown_fence_removes_json_fence():
    text = "```json\n[]\n```"
    assert _strip_markdown_fence(text) == "[]"


def test_strip_markdown_fence_removes_bare_fence():
    text = "```\n[]\n```"
    assert _strip_markdown_fence(text) == "[]"


def test_strip_markdown_fence_no_fence_passthrough():
    assert _strip_markdown_fence(" [] ") == "[]"


def test_extract_array_finds_array_after_prose():
    text = 'Sure, here you go:\n[{"subject": "x"}]\nLet me know if...'
    arr = _extract_array(text)
    assert arr == '[{"subject": "x"}]'


def test_extract_array_handles_nested_objects_with_brackets_in_strings():
    text = '[{"obj": "GET /api/[id]"}, {"obj": "y"}]'
    arr = _extract_array(text)
    assert arr == text


def test_extract_array_returns_none_when_no_open_bracket():
    assert _extract_array("just prose") is None


def test_extract_array_returns_none_on_unclosed_bracket():
    assert _extract_array("[unclosed") is None


# --- triple parsing -------------------------------------------------------


def test_parse_triples_basic():
    text = (
        '[{"subject": "my-app", "predicate": "uses", '
        '"object": "fastapi", "confidence": 0.9}]'
    )
    triples = _parse_triples(text=text, source_project="my-app", max_triples=10)
    assert len(triples) == 1
    t = triples[0]
    assert t.subject == "my-app"
    assert t.predicate == "uses"
    assert t.obj == "fastapi"
    assert t.confidence == 0.9


def test_parse_triples_tolerates_obj_alias():
    """Some models autofill the dataclass field name `obj` instead of `object`."""
    text = '[{"subject": "x", "predicate": "uses", "obj": "y", "confidence": 0.8}]'
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert len(triples) == 1
    assert triples[0].obj == "y"


def test_parse_triples_drops_malformed_records():
    """Records missing predicate or object are silently dropped; the rest survive."""
    text = """[
        {"subject": "x", "predicate": "uses", "object": "fastapi"},
        {"subject": "x"},
        {"predicate": "uses", "object": "click"},
        {"subject": "x", "predicate": "", "object": "empty-pred"},
        {"subject": "x", "predicate": "exposes", "object": "GET /v1/foo"}
    ]"""
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert len(triples) == 3
    objects = [t.obj for t in triples]
    assert "fastapi" in objects
    assert "click" in objects
    assert "GET /v1/foo" in objects


def test_parse_triples_default_subject_falls_back_to_source():
    text = '[{"predicate": "uses", "object": "fastapi"}]'
    triples = _parse_triples(text=text, source_project="my-app", max_triples=10)
    assert len(triples) == 1
    assert triples[0].subject == "my-app"


def test_parse_triples_clamps_confidence_to_unit_range():
    text = """[
        {"subject": "x", "predicate": "uses", "object": "a", "confidence": 1.5},
        {"subject": "x", "predicate": "uses", "object": "b", "confidence": -0.2}
    ]"""
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert len(triples) == 2
    assert triples[0].confidence == 1.0
    assert triples[1].confidence == 0.0


def test_parse_triples_default_confidence_when_missing():
    text = '[{"subject": "x", "predicate": "uses", "object": "fastapi"}]'
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert triples[0].confidence == 0.7


def test_parse_triples_caps_at_max_triples():
    text = "[" + ",".join(
        f'{{"subject": "x", "predicate": "uses", "object": "{i}"}}' for i in range(50)
    ) + "]"
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert len(triples) == 10


def test_parse_triples_top_level_non_array_returns_empty():
    text = '{"subject": "x"}'
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert triples == []


def test_parse_triples_invalid_json_returns_empty():
    text = "[this is not, valid, json,"
    triples = _parse_triples(text=text, source_project="x", max_triples=10)
    assert triples == []


def test_parse_triples_no_array_returns_empty():
    triples = _parse_triples(text="just prose", source_project="x", max_triples=10)
    assert triples == []


# --- extract_via_llm orchestration ---------------------------------------


def test_extract_via_llm_passes_through_to_backend(tmp_path: Path):
    backend = FakeBackend(
        response='[{"subject": "x", "predicate": "uses", "object": "fastapi"}]'
    )
    triples = extract_via_llm(
        answer="we use fastapi for the API",
        source_project="x",
        backend=backend,
        cwd=tmp_path,
        max_triples=20,
    )
    assert len(triples) == 1
    assert triples[0].obj == "fastapi"
    assert backend.last_prompt is not None
    assert "we use fastapi for the API" in backend.last_prompt


def test_extract_via_llm_returns_empty_for_short_answer(tmp_path: Path):
    backend = MagicMock()
    triples = extract_via_llm(
        answer="hi",
        source_project="x",
        backend=backend,
        cwd=tmp_path,
    )
    assert triples == []
    backend.ask_local.assert_not_called()


def test_extract_via_llm_returns_empty_on_backend_error(tmp_path: Path):
    backend = FakeBackend(raises=BackendError("boom", code="exit_nonzero"))
    triples = extract_via_llm(
        answer="A long enough answer to clear the threshold",
        source_project="x",
        backend=backend,
        cwd=tmp_path,
    )
    assert triples == []


def test_extract_via_llm_returns_empty_on_garbage_response(tmp_path: Path):
    backend = FakeBackend(response="I refuse to extract triples today.")
    triples = extract_via_llm(
        answer="A long enough answer to clear the threshold",
        source_project="x",
        backend=backend,
        cwd=tmp_path,
    )
    assert triples == []


def test_extract_via_llm_handles_markdown_fence(tmp_path: Path):
    backend = FakeBackend(
        response='```json\n[{"subject": "x", "predicate": "uses", "object": "click"}]\n```'
    )
    triples = extract_via_llm(
        answer="A reasonably long answer here to clear the threshold",
        source_project="x",
        backend=backend,
        cwd=tmp_path,
    )
    assert len(triples) == 1
    assert triples[0].obj == "click"
