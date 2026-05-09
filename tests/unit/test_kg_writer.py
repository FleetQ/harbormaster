"""Tests for harbormaster.fleetq.kg.KGWriter.

Mirrors test_memory_writeback.py's MemoryWriter tests for the
KG-discriminated payload + write_triples batch behaviour.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")

from harbormaster.fleetq.kg import KGWriter, Triple  # noqa: E402


def _writer_with_transport(handler) -> KGWriter:
    transport = httpx.MockTransport(handler)
    w = KGWriter(base_url="http://fake", api_token="token")
    w._client = httpx.Client(
        base_url="http://fake",
        transport=transport,
        timeout=5.0,
        headers={
            "Authorization": "Bearer token",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    return w


# --- single triple ----------------------------------------------------------


def test_kg_writer_posts_triple_with_kg_discriminator():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(201, json={"id": "abc"})

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_triple(
            triple=Triple(
                subject="alpha",
                predicate="uses",
                obj="pydantic",
                confidence=0.55,
            ),
            project_name="alpha",
            host=None,
            source_tool="ask_project",
            metadata={"answer_chars": 234},
        )
    finally:
        writer.close()

    assert ok is True
    assert captured["method"] == "POST"
    assert captured["url"] == "http://fake/api/v1/memory"
    assert captured["auth"] == "Bearer token"
    body = captured["body"]
    assert '"type":"kg_triple"' in body
    assert '"tool":"ask_project"' in body
    assert '"project":"alpha"' in body
    assert '"host":"local"' in body
    assert '"subject":"alpha"' in body
    assert '"predicate":"uses"' in body
    assert '"object":"pydantic"' in body
    assert '"answer_chars":234' in body


def test_kg_writer_returns_false_on_4xx_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(403, text="forbidden")

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_triple(
            triple=Triple(subject="x", predicate="uses", obj="y"),
            project_name="x",
            host="friday",
        )
    finally:
        writer.close()
    assert ok is False


def test_kg_writer_returns_false_on_network_error_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_triple(
            triple=Triple(subject="x", predicate="uses", obj="y"),
            project_name="x",
            host=None,
        )
    finally:
        writer.close()
    assert ok is False


def test_kg_writer_requires_base_url_and_token():
    with pytest.raises(ValueError, match="base_url"):
        KGWriter(base_url="", api_token="x")
    with pytest.raises(ValueError, match="api_token"):
        KGWriter(base_url="http://x", api_token="")


# --- batch write_triples ----------------------------------------------------


def test_write_triples_returns_count_of_successes():
    """write_triples should keep going past individual failures and
    return the count that actually landed."""
    posted: list[dict[str, object]] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # Reject the second call to simulate a flaky FleetQ side.
        if call_count["n"] == 2:
            return httpx.Response(500, text="oops")
        posted.append({"body": request.content.decode()})
        return httpx.Response(201, json={"id": str(call_count["n"])})

    writer = _writer_with_transport(handler)
    try:
        ok_count = writer.write_triples(
            triples=[
                Triple(subject="x", predicate="uses", obj="lib1"),
                Triple(subject="x", predicate="uses", obj="lib2"),
                Triple(subject="x", predicate="uses", obj="lib3"),
            ],
            project_name="x",
            host=None,
        )
    finally:
        writer.close()

    # 3 calls attempted, the middle one rejected — count = 2
    assert call_count["n"] == 3
    assert ok_count == 2


def test_write_triples_empty_list_returns_zero():
    writer = _writer_with_transport(lambda r: httpx.Response(200))
    try:
        assert writer.write_triples(
            triples=[], project_name="x", host=None
        ) == 0
    finally:
        writer.close()


# --- Triple dataclass ------------------------------------------------------


def test_triple_as_dict_includes_confidence():
    t = Triple(subject="a", predicate="uses", obj="b", confidence=0.42)
    d = t.as_dict()
    assert d == {
        "subject": "a",
        "predicate": "uses",
        "object": "b",
        "confidence": 0.42,
    }


def test_triple_default_confidence_is_one():
    t = Triple(subject="a", predicate="x", obj="b")
    assert t.confidence == 1.0
