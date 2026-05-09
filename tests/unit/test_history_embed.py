"""Tests for harbormaster.history.embed (backend selection)."""
from __future__ import annotations

import pytest

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history import FastembedBackend, FTS5Backend, get_embedding_backend


def test_fts5_backend_returns_none():
    b = FTS5Backend()
    assert b.encode("anything") is None
    assert b.dim == 0
    assert b.name == "fts5"


def test_get_embedding_backend_returns_fts5_when_configured():
    config = HarbormasterConfig(history=HistoryConfig(enabled=True, embedding_backend="fts5"))
    b = get_embedding_backend(config)
    assert b.name == "fts5"


def test_get_embedding_backend_returns_fastembed_when_configured():
    """When fastembed is installed (dev extra), the fastembed backend
    is constructed (model is NOT loaded yet — lazy on first encode)."""
    config = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fastembed")
    )
    b = get_embedding_backend(config)
    assert b.name == "fastembed"
    assert b.dim == 384


def test_get_embedding_backend_falls_back_when_fastembed_missing(monkeypatch):
    """Simulate `fastembed` not installed → should fall back to FTS5."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kw):
        if name == "fastembed":
            raise ImportError("simulated missing fastembed")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    config = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fastembed")
    )
    b = get_embedding_backend(config)
    assert b.name == "fts5"


def test_fastembed_backend_raises_runtime_error_when_missing(monkeypatch):
    """If FastembedBackend is constructed but fastembed is missing
    (e.g. user pinned it via embed_backend = 'fastembed' but didn't
    install the extra), encode() raises RuntimeError with a helpful
    message."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kw):
        if name == "fastembed":
            raise ImportError("simulated missing fastembed")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    backend = FastembedBackend()
    with pytest.raises(RuntimeError, match="fastembed is not installed"):
        backend.encode("hello")
