"""Tests for harbormaster.fleetq.triples heuristic extractors."""
from __future__ import annotations

from harbormaster.fleetq.triples import (
    extract_all,
    extract_endpoints,
    extract_project_mentions,
    extract_uses,
)

# --- project mentions -----------------------------------------------------


def test_mentions_finds_known_project_name():
    out = extract_project_mentions(
        answer="The alpha service talks to the beta service over HTTP.",
        source_project="other",
        known_projects=["alpha", "beta", "gamma"],
    )
    objects = {t.obj for t in out}
    assert objects == {"alpha", "beta"}
    # gamma is not mentioned
    assert all(t.subject == "other" for t in out)
    assert all(t.predicate == "mentions" for t in out)


def test_mentions_excludes_source_project():
    out = extract_project_mentions(
        answer="alpha describes alpha and references beta.",
        source_project="alpha",
        known_projects=["alpha", "beta"],
    )
    objects = {t.obj for t in out}
    assert objects == {"beta"}


def test_mentions_handles_hyphenated_names():
    out = extract_project_mentions(
        answer="agent-fleet-cloud and harbormaster-mcp share storage.",
        source_project="other",
        known_projects=["agent-fleet-cloud", "harbormaster-mcp"],
    )
    objects = {t.obj for t in out}
    assert objects == {"agent-fleet-cloud", "harbormaster-mcp"}


def test_mentions_dedupes_repeated_mentions():
    out = extract_project_mentions(
        answer="alpha alpha alpha alpha alpha.",
        source_project="x",
        known_projects=["alpha"],
    )
    assert len(out) == 1


def test_mentions_recognises_composer_short_alias():
    """A composer-style `vendor/pkg` known project should also match
    a bare `pkg` mention."""
    out = extract_project_mentions(
        answer="See pkg for details.",
        source_project="other",
        known_projects=["vendor/pkg"],
    )
    assert len(out) == 1
    assert out[0].obj == "vendor/pkg"


def test_mentions_returns_empty_when_no_known_projects():
    assert extract_project_mentions(
        answer="lots of words here", source_project="x", known_projects=[]
    ) == []


# --- uses -----------------------------------------------------------------


def test_uses_picks_up_uses_the_x_library():
    out = extract_uses(
        answer="It uses the requests library for HTTP.",
        source_project="alpha",
    )
    assert len(out) == 1
    assert out[0].obj == "requests"


def test_uses_picks_up_depends_on():
    out = extract_uses(
        answer="The service depends on pydantic for validation.",
        source_project="alpha",
    )
    assert any(t.obj == "pydantic" for t in out)


def test_uses_picks_up_built_on():
    out = extract_uses(
        answer="The dashboard is built on FastAPI under the hood.",
        source_project="alpha",
    )
    assert any(t.obj.lower() == "fastapi" for t in out)


def test_uses_dedupes_same_lib_in_multiple_phrasings():
    out = extract_uses(
        answer="It uses the redis library and depends on redis for caching.",
        source_project="alpha",
    )
    assert len([t for t in out if t.obj.lower() == "redis"]) == 1


def test_uses_returns_empty_on_unrelated_text():
    out = extract_uses(
        answer="This is a description of something with no library mentions.",
        source_project="alpha",
    )
    assert out == []


# --- endpoints ------------------------------------------------------------


def test_endpoints_extracts_get_path():
    out = extract_endpoints(
        answer="The service exposes GET /api/projects for listing.",
        source_project="alpha",
    )
    assert len(out) == 1
    assert out[0].obj == "GET /api/projects"


def test_endpoints_extracts_multiple_methods():
    out = extract_endpoints(
        answer="Endpoints: GET /a, POST /b, DELETE /c/{id}.",
        source_project="alpha",
    )
    objects = {t.obj for t in out}
    assert objects == {"GET /a", "POST /b", "DELETE /c/{id}"}


def test_endpoints_dedupes_repeated_path():
    out = extract_endpoints(
        answer="POST /mcp/server is the entry. POST /mcp/server is documented in detail.",
        source_project="alpha",
    )
    assert len(out) == 1


def test_endpoints_ignores_paths_without_http_method():
    out = extract_endpoints(
        answer="The /api/foo path is just text without a method prefix.",
        source_project="alpha",
    )
    assert out == []


def test_endpoints_strips_trailing_punctuation():
    out = extract_endpoints(
        answer="Hits POST /v1/foo, then GET /v1/bar.",
        source_project="alpha",
    )
    objects = {t.obj for t in out}
    assert objects == {"POST /v1/foo", "GET /v1/bar"}


# --- extract_all combined --------------------------------------------------


def test_extract_all_combines_all_extractors():
    out = extract_all(
        answer=(
            "myapp uses the requests library. "
            "It exposes GET /api/v1/items. "
            "Talks to billing-service over HTTP."
        ),
        source_project="myapp",
        known_projects=["billing-service"],
    )
    predicates = {t.predicate for t in out}
    assert {"mentions", "uses", "exposes"} <= predicates


def test_extract_all_caps_at_max_triples():
    """When the answer is dense enough to exceed the cap, the
    extractor returns at most max_triples (mentions first by design)."""
    answer = " ".join(f"alpha-{i}" for i in range(100))  # all "mentions"
    known = [f"alpha-{i}" for i in range(100)]
    out = extract_all(
        answer=answer,
        source_project="src",
        known_projects=known,
        max_triples=10,
    )
    assert len(out) == 10
    assert all(t.predicate == "mentions" for t in out)
