"""recall_qa MCP tool — semantic / lexical recall over the per-host Q&A store."""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig

logger = logging.getLogger("harbormaster.tools.recall")


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def recall_qa(
        question: str,
        top_k: int | None = None,
        host: str | None = None,
        project: str | None = None,
        min_similarity: float | None = None,
    ) -> dict[str, object]:
        """Recall prior Q&A trajectories that semantically match `question`.

        Searches the per-host sqlite store written by ask_project /
        delegate_task. When [history].embedding_backend = "fastembed"
        and the package is installed, ranks by cosine similarity over
        question embeddings; otherwise falls back to FTS5 / bm25
        lexical recall. Returns a dict with `enabled`, `backend`,
        `host`, and `matches` (list of dicts).

        When [history] is disabled, returns `{enabled: false, ...}`
        and an empty matches list.

        Args:
          question: free-text query (required)
          top_k: max matches to return (default from config)
          host: which host's store to search (default: "local")
          project: filter to one project name
          min_similarity: drop hits below this score (vec path only;
            ignored on FTS5 fallback). 0.0..1.0
        """
        if not config.history.enabled:
            return {
                "enabled": False,
                "backend": None,
                "host": host or "local",
                "matches": [],
                "message": "[history] is disabled in config; set [history].enabled = true",
            }

        try:
            from harbormaster.history import (
                QAStore,
                get_embedding_backend,
            )
        except ImportError:
            return {
                "enabled": False,
                "backend": None,
                "host": host or "local",
                "matches": [],
                "message": "the [history] extra is not installed; "
                "install with `pip install harbormaster-mcp[history]`",
            }

        effective_top_k = top_k if top_k is not None else config.history.default_top_k
        effective_min_sim = (
            min_similarity
            if min_similarity is not None
            else config.history.default_min_similarity
        )

        try:
            backend = get_embedding_backend(config)
            store = QAStore.open(
                db_dir=config.history.db_dir,
                host=host,
                embedding_backend=backend,
                embedding_dim=config.history.embedding_dim,
            )
        except Exception as e:
            logger.exception("opening history store failed")
            return {
                "enabled": True,
                "backend": None,
                "host": host or "local",
                "matches": [],
                "message": f"history store unavailable: {e}",
            }

        try:
            matches = store.recall(
                question=question,
                top_k=effective_top_k,
                project=project,
                min_similarity=effective_min_sim,
            )
        except Exception as e:
            logger.exception("history recall failed")
            store.close()
            return {
                "enabled": True,
                "backend": backend.name,
                "host": host or "local",
                "matches": [],
                "message": f"recall failed: {e}",
            }

        store.close()
        return {
            "enabled": True,
            "backend": backend.name,
            "host": host or "local",
            "matches": [m.to_dict() for m in matches],
        }
