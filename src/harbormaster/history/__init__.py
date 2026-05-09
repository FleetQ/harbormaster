"""Q&A history with semantic recall (v1.2 phase 1).

Per-host sqlite store of (question, answer, project, host, tool, ...)
records. When the optional [history] extra is installed and
[history].embedding_backend = "fastembed", question embeddings are
stored in a sqlite-vec virtual table for cosine-similarity recall.
Otherwise the store falls back to FTS5 / bm25 lexical recall.

Three-gate opt-in (mirrors [fleetq] pattern):
  1. [history] enabled = true
  2. per-tool log_<tool> = true (default true for all tools)
  3. the [history] extra installed (sqlite-vec + optionally fastembed)

Public surface:
  - QAStore: record / recall / prune
  - get_embedding_backend(config): returns the configured backend or None
  - QARecord, QAMatch: pydantic data classes for the wire shape
"""
from __future__ import annotations

from harbormaster.history.auto_reembed import (
    ReembedState,
    maybe_start_auto_reembed_thread,
    trigger_manual_reembed,
)
from harbormaster.history.auto_reembed import (
    read_state as read_reembed_state,
)
from harbormaster.history.embed import (
    EmbeddingBackend,
    FastembedBackend,
    FTS5Backend,
    get_embedding_backend,
)
from harbormaster.history.schema import (
    HISTORY_VEC_DIM,
    EmbeddingMeta,
    connect,
    ensure_schema,
    read_embedding_meta,
    write_embedding_meta,
)
from harbormaster.history.store import QAMatch, QARecord, QAStore

__all__ = [
    "EmbeddingBackend",
    "EmbeddingMeta",
    "FastembedBackend",
    "FTS5Backend",
    "HISTORY_VEC_DIM",
    "QAMatch",
    "QARecord",
    "QAStore",
    "ReembedState",
    "connect",
    "ensure_schema",
    "get_embedding_backend",
    "maybe_start_auto_reembed_thread",
    "read_embedding_meta",
    "read_reembed_state",
    "trigger_manual_reembed",
    "write_embedding_meta",
]
