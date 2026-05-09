"""recall_qa MCP tool — semantic / lexical recall over the per-host Q&A store."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig

if TYPE_CHECKING:
    from harbormaster.history import EmbeddingBackend, QAMatch

logger = logging.getLogger("harbormaster.tools.recall")


def _recall_one_host(
    *,
    config: HarbormasterConfig,
    host: str | None,
    question: str,
    top_k: int,
    project: str | None,
    min_similarity: float,
    backend: EmbeddingBackend,
) -> tuple[list[QAMatch], str | None]:
    """Open one per-host store, run recall, return (matches, error).

    Errors during open/recall are caught + logged so a single bad
    host's store doesn't poison cross-host aggregation. The returned
    error string is None on success, otherwise a one-line message
    suitable for inclusion in the tool's `messages` array.
    """
    from harbormaster.history import QAStore

    try:
        store = QAStore.open(
            db_dir=config.history.db_dir,
            host=host,
            embedding_backend=backend,
            embedding_dim=config.history.embedding_dim,
        )
    except Exception as e:
        logger.exception(
            "opening history store failed for host=%s",
            host if host is not None else "local",
        )
        return [], f"open failed: {e}"

    try:
        matches = store.recall(
            question=question,
            top_k=top_k,
            project=project,
            min_similarity=min_similarity,
        )
    except Exception as e:
        logger.exception(
            "history recall failed for host=%s",
            host if host is not None else "local",
        )
        store.close()
        return [], f"recall failed: {e}"

    store.close()
    return matches, None


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

        v2.0.0a6: pass `host="all"` to fan out across the local store
        + every configured `[hosts.*]` store; results are score-merged
        and capped at `top_k`. Each match retains its original `host`
        field so callers can attribute hits to the right machine.

        Args:
          question: free-text query (required)
          top_k: max matches to return (default from config). When
            `host="all"`, this caps the merged result, NOT each per-host
            recall.
          host: which host's store to search. "local" / None — local
            store; a configured host label — that host; "all" — every
            store including local (v2.0.0a6).
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
            from harbormaster.history import get_embedding_backend
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

        backend = get_embedding_backend(config)

        # v2.0.0a6: cross-host fan-out. host="all" iterates over local +
        # every configured host. Each host gets its own per-host db
        # locally (db filename includes the host label) — we don't SSH
        # for recall; the harbormaster process records per-host on its
        # own machine and reads back from the same files.
        if host == "all":
            targets: list[str | None] = [None, *sorted(config.hosts.keys())]
            all_matches: list[QAMatch] = []
            errors: dict[str, str] = {}
            for target in targets:
                # Per-host fetch uses the configured top_k unmodified —
                # over-fetching slightly so the global score sort has
                # enough headroom across hosts.
                per_host_matches, err = _recall_one_host(
                    config=config,
                    host=target,
                    question=question,
                    top_k=effective_top_k,
                    project=project,
                    min_similarity=effective_min_sim,
                    backend=backend,
                )
                if err is not None:
                    errors[target if target is not None else "local"] = err
                    continue
                all_matches.extend(per_host_matches)
            # Score-sort across hosts, then cap.
            all_matches.sort(key=lambda m: m.score, reverse=True)
            merged = all_matches[:effective_top_k]
            result: dict[str, object] = {
                "enabled": True,
                "backend": backend.name,
                "host": "all",
                "hosts_searched": [t if t is not None else "local" for t in targets],
                "matches": [m.to_dict() for m in merged],
            }
            if errors:
                result["errors"] = errors
            return result

        # Single-host (default v1 behaviour) — same path as before.
        matches, err = _recall_one_host(
            config=config,
            host=host,
            question=question,
            top_k=effective_top_k,
            project=project,
            min_similarity=effective_min_sim,
            backend=backend,
        )
        if err is not None:
            return {
                "enabled": True,
                "backend": backend.name,
                "host": host or "local",
                "matches": [],
                "message": err,
            }
        return {
            "enabled": True,
            "backend": backend.name,
            "host": host or "local",
            "matches": [m.to_dict() for m in matches],
        }
