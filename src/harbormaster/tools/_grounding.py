"""Cross-session memory recall for the claude -p prompt builder (v1.2 phase 4).

`build_grounded_prompt(question, project, host, config)` prepends a
"Prior context" section to the user's question with the top-K
`recall_qa` matches from the per-host sqlite store. Auto-grounds the
subagent in past answers without manual context loading.

Three opt-in gates:
  1. `[history] enabled = true`
  2. `[history] auto_ground = true` (default false; opt-in even when
     history is enabled, since prompt bloat has cost implications)
  3. `harbormaster.history` package importable

Failures are silent: if the store is missing, recall throws, or
embedding fails, the original question is returned unchanged. Same
fire-and-forget semantics as the trajectory writeback hooks — better
to ask the question without context than to fail the whole tool call.

A character cap (`[history] auto_ground_max_chars`, default 8000 ≈ 2k
tokens) keeps the prepended context bounded. Matches are truncated
oldest-first when the cap is hit.
"""
from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harbormaster.config import HarbormasterConfig
    from harbormaster.history import QAMatch

logger = logging.getLogger("harbormaster.tools._grounding")


_HEADER = "<<<PRIOR CONTEXT (auto-loaded by harbormaster from past answers)>>>"
_FOOTER = "<<<END PRIOR CONTEXT>>>"


def build_grounded_prompt(
    *,
    question: str,
    project: str,
    host: str | None,
    config: HarbormasterConfig,
) -> str:
    """Return `question` with a prior-context section prepended when
    auto-grounding is enabled and prior matches are found. Otherwise
    returns `question` unchanged.
    """
    if not config.history.enabled or not config.history.auto_ground:
        return question

    try:
        from harbormaster.history import (
            QAStore,
            get_embedding_backend,
        )
    except ImportError:
        return question

    try:
        backend = get_embedding_backend(config)
        store = QAStore.open(
            db_dir=config.history.db_dir,
            host=host,
            embedding_backend=backend,
            embedding_dim=config.history.embedding_dim,
        )
    except Exception:
        logger.exception("auto-ground: opening history store failed; passthrough")
        return question

    try:
        matches = store.recall(
            question=question,
            top_k=config.history.auto_ground_top_k,
            project=project,
            min_similarity=config.history.auto_ground_min_similarity,
        )
    except Exception:
        logger.exception("auto-ground: recall failed; passthrough")
        store.close()
        return question
    finally:
        # store.close() is also called inside the except branch above
        # — guarded with contextlib.suppress to avoid double-closing or
        # propagating a close-time error.
        with contextlib.suppress(Exception):
            store.close()

    if not matches:
        return question

    return _format_grounded(
        question=question,
        matches=matches,
        max_chars=config.history.auto_ground_max_chars,
    )


def _format_grounded(*, question: str, matches: list[QAMatch], max_chars: int) -> str:
    """Render the prior-context block + the original question. When
    the rendered context exceeds max_chars, drop the lowest-scored
    matches first until it fits."""
    # Sort by score descending so we keep the strongest matches when
    # the cap forces trimming.
    ranked = sorted(matches, key=lambda m: m.score, reverse=True)

    sections: list[str] = []
    used_chars = 0
    overhead = len(_HEADER) + len(_FOOTER) + 32  # header/footer + separators

    for m in ranked:
        block = _render_one(m)
        if used_chars + len(block) + overhead > max_chars:
            break
        sections.append(block)
        used_chars += len(block)

    if not sections:
        # Even the strongest single match exceeds the cap — fall back
        # to passthrough rather than emit a misleading empty context.
        return question

    body = "\n\n".join(sections)
    return f"{_HEADER}\n\n{body}\n\n{_FOOTER}\n\n{question}"


def _render_one(match: QAMatch) -> str:
    """One match → markdown subsection."""
    score_str = f"{match.score:.2f}"
    answer = match.answer.strip()
    # Trim absurdly long historical answers so a single huge match
    # doesn't crowd out two smaller useful ones.
    if len(answer) > 1500:
        answer = answer[:1500].rstrip() + "  …[truncated]"
    return (
        f"### Past Q (project={match.project}, "
        f"tool={match.tool}, score={score_str})\n"
        f"**Question:** {match.question.strip()}\n\n"
        f"**Answer:** {answer}"
    )
