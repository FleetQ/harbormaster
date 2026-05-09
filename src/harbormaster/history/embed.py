"""Embedding backends for the Q&A history store.

Two implementations:

  * FastembedBackend — runs BAAI/bge-small-en-v1.5 locally via fastembed.
    Lazy model load on first encode; ~50MB ONNX model downloaded once
    to the user's HF cache.
  * FTS5Backend — no-op placeholder used when fastembed is unavailable
    or [history].embedding_backend = "fts5". `encode()` returns None,
    signalling the store to use bm25 lexical recall instead.

The store decides which path to take based on whether `encode()`
returns a vector or None.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from harbormaster.config import HarbormasterConfig

logger = logging.getLogger("harbormaster.history.embed")


class EmbeddingBackend(Protocol):
    """A backend that turns text into a fixed-length float vector or
    returns None when no embedding is available (FTS5 fallback)."""

    name: str
    dim: int

    @property
    def signature(self) -> str:
        """Canonical identifier for the embedding model that produced
        a given vector. Used by the QAStore embedding-drift detector
        (v2.0.0a2) to detect when the configured model changed and a
        re-embed is needed."""
        ...

    def encode(self, text: str) -> list[float] | None: ...


class FTS5Backend:
    """No-embedding backend. The store treats `encode() is None` as a
    signal to consult the FTS5 auxiliary index instead of qa_vec."""

    name = "fts5"
    dim = 0

    @property
    def signature(self) -> str:
        return "fts5"

    def encode(self, text: str) -> list[float] | None:
        return None


class FastembedBackend:
    """Lazy-loaded fastembed.TextEmbedding wrapper.

    The embedding model is constructed on first encode call to keep
    `harbormaster-mcp --version` and config-validation paths free of
    the ~50MB model download.
    """

    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.model = model
        self.dim = dim
        self._impl: Any | None = None

    @property
    def signature(self) -> str:
        return f"fastembed/{self.model}"

    def _ensure_impl(self) -> Any:
        if self._impl is not None:
            return self._impl
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed; install with `pip install harbormaster-mcp[history]` "
                "or set [history].embedding_backend = \"fts5\""
            ) from e
        self._impl = TextEmbedding(model_name=self.model)
        return self._impl

    def encode(self, text: str) -> list[float] | None:
        impl = self._ensure_impl()
        # fastembed yields numpy arrays; coerce to list[float] so the
        # store can pass them straight to sqlite-vec.
        embeddings = list(impl.embed([text]))
        if not embeddings:
            return None
        vec = embeddings[0]
        return [float(x) for x in vec]


def get_embedding_backend(config: HarbormasterConfig) -> EmbeddingBackend:
    """Return the configured embedding backend.

    Falls back to FTS5Backend when fastembed is requested but the
    package is unavailable (fail-soft so the rest of the feature
    keeps working).
    """
    if config.history.embedding_backend == "fastembed":
        try:
            import fastembed  # noqa: F401
        except ImportError:
            logger.warning(
                "[history].embedding_backend = 'fastembed' but fastembed is not "
                "installed; falling back to FTS5 / bm25"
            )
            return FTS5Backend()
        return FastembedBackend(
            model=config.history.fastembed_model,
            dim=config.history.embedding_dim,
        )
    return FTS5Backend()
