"""Tests for harbormaster.tools._grounding.build_grounded_prompt."""
from __future__ import annotations

from pathlib import Path

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history import FTS5Backend, QARecord, QAStore
from harbormaster.tools._grounding import build_grounded_prompt


def _config(tmp_path: Path, *, enabled: bool = True, auto_ground: bool = True, **history_kw) -> HarbormasterConfig:
    return HarbormasterConfig(
        history=HistoryConfig(
            enabled=enabled,
            auto_ground=auto_ground,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
            **history_kw,
        )
    )


def _seed(tmp_path: Path, host: str | None, *records: QARecord) -> None:
    store = QAStore.open(
        db_dir=tmp_path, host=host, embedding_backend=FTS5Backend(),
    )
    try:
        for rec in records:
            store.record(rec)
    finally:
        store.close()


def _make_record(question: str, answer: str = "stub answer", project: str = "alpha") -> QARecord:
    return QARecord(
        question=question,
        answer=answer,
        project=project,
        host="local",
        tool="ask_project",
    )


# --- passthrough cases ---------------------------------------------------


def test_passthrough_when_history_disabled(tmp_path: Path):
    config = _config(tmp_path, enabled=False)
    out = build_grounded_prompt(
        question="hello", project="alpha", host=None, config=config,
    )
    assert out == "hello"


def test_passthrough_when_auto_ground_disabled(tmp_path: Path):
    config = _config(tmp_path, enabled=True, auto_ground=False)
    out = build_grounded_prompt(
        question="hello", project="alpha", host=None, config=config,
    )
    assert out == "hello"


def test_passthrough_when_no_matches(tmp_path: Path):
    """history enabled + auto_ground enabled but empty store → no-op."""
    config = _config(tmp_path)
    out = build_grounded_prompt(
        question="anything", project="alpha", host=None, config=config,
    )
    assert out == "anything"


def test_passthrough_when_no_matches_for_project(tmp_path: Path):
    """history has matches but for a different project → no-op."""
    _seed(tmp_path, None, _make_record("hello world", "answer", project="other"))
    config = _config(tmp_path)
    out = build_grounded_prompt(
        question="hello", project="alpha", host=None, config=config,
    )
    assert out == "hello"


# --- happy path ----------------------------------------------------------


def test_grounded_prepends_prior_context(tmp_path: Path):
    _seed(tmp_path, None, _make_record(
        "How does authentication work in alpha?",
        "JWT-based — see auth.md",
        project="alpha",
    ))
    config = _config(tmp_path)
    out = build_grounded_prompt(
        question="Tell me about authentication",
        project="alpha", host=None, config=config,
    )
    assert "PRIOR CONTEXT" in out
    assert "END PRIOR CONTEXT" in out
    assert "JWT-based" in out
    # Original question must remain at the end:
    assert out.endswith("Tell me about authentication")


def test_grounded_filters_by_project(tmp_path: Path):
    """Records under different projects should NOT appear in the
    grounded prompt for project=alpha."""
    _seed(
        tmp_path, None,
        _make_record("authentication q", "alpha-answer", project="alpha"),
        _make_record("authentication q", "beta-answer", project="beta"),
    )
    config = _config(tmp_path)
    out = build_grounded_prompt(
        question="authentication", project="alpha", host=None, config=config,
    )
    assert "alpha-answer" in out
    assert "beta-answer" not in out


def test_grounded_respects_top_k_config(tmp_path: Path):
    _seed(
        tmp_path, None,
        _make_record("auth feature 1", "answer-1"),
        _make_record("auth feature 2", "answer-2"),
        _make_record("auth feature 3", "answer-3"),
        _make_record("auth feature 4", "answer-4"),
        _make_record("auth feature 5", "answer-5"),
    )
    config = _config(tmp_path, auto_ground_top_k=2)
    out = build_grounded_prompt(
        question="auth", project="alpha", host=None, config=config,
    )
    # At most 2 prior-Q sections
    assert out.count("### Past Q") <= 2


def test_grounded_caps_at_max_chars(tmp_path: Path):
    """Many matches with long answers → cap kicks in. Result must
    still be valid (header + at least one match + footer + question)."""
    long_answer = "A" * 1200
    _seed(
        tmp_path, None,
        _make_record("auth feature 1", long_answer),
        _make_record("auth feature 2", long_answer),
        _make_record("auth feature 3", long_answer),
    )
    config = _config(tmp_path, auto_ground_max_chars=2000, auto_ground_top_k=10)
    out = build_grounded_prompt(
        question="auth", project="alpha", host=None, config=config,
    )
    # Must still produce a valid output, not error
    assert "PRIOR CONTEXT" in out
    assert out.endswith("auth")
    # Roughly bounded — we allow some overhead beyond max_chars
    assert len(out) < 5000


def test_grounded_truncates_huge_individual_answer(tmp_path: Path):
    """A single huge answer should be truncated, not allowed to crowd
    the output."""
    huge = "X" * 5000
    _seed(tmp_path, None, _make_record("auth question", huge))
    config = _config(tmp_path, auto_ground_max_chars=10000)
    out = build_grounded_prompt(
        question="auth", project="alpha", host=None, config=config,
    )
    assert "[truncated]" in out


# --- failure swallowing --------------------------------------------------


def test_grounded_passthrough_on_store_open_failure(tmp_path: Path, monkeypatch):
    """If QAStore.open raises, build_grounded_prompt must not propagate."""
    config = _config(tmp_path)

    def explode(*_args, **_kw):
        raise RuntimeError("store boom")

    monkeypatch.setattr(
        "harbormaster.history.QAStore.open",
        classmethod(lambda *a, **kw: explode()),
    )

    out = build_grounded_prompt(
        question="anything", project="alpha", host=None, config=config,
    )
    assert out == "anything"


def test_grounded_passthrough_on_recall_failure(tmp_path: Path, monkeypatch):
    """If QAStore.recall raises, build_grounded_prompt must not propagate."""
    _seed(tmp_path, None, _make_record("hello", "world"))
    config = _config(tmp_path)

    real_open = QAStore.open

    class ExplodingStore:
        def __init__(self, real):
            self._real = real

        def recall(self, **_kw):
            raise RuntimeError("recall boom")

        def close(self):
            self._real.close()

    @classmethod
    def open_exploding(cls, **kw):
        return ExplodingStore(real_open(**kw))

    monkeypatch.setattr(QAStore, "open", open_exploding)

    out = build_grounded_prompt(
        question="hello", project="alpha", host=None, config=config,
    )
    assert out == "hello"
