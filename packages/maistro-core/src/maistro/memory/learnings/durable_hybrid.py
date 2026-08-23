"""Hybrid search whose vectors survive a restart (#188).

`HybridLearningStore` holds embeddings in a process-local
`dict[int, list[float]]`. Everything it computes is discarded when the process
ends, so the first read after every restart re-embeds the whole working set —
paying for the model call again to rebuild state the database was already
holding the rows for. That is the gap the column closes, and this is the class
that uses it.

Wrapping rather than replacing: `PgLearningStore` owns the SQL and the scope
rules, and both are things this must not reimplement. The only behaviour added
here is "compute a vector on write, use it on read".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.memory.vectors import require_matching_dimension

if TYPE_CHECKING:
    from maistro.persistence.pg_learnings import PgLearningStore
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.types.memory import Learning

logger = logging.getLogger("maistro.memory.learnings.durable_hybrid")


class DurableHybridLearningStore:
    """`PgLearningStore` plus embeddings written to, and read from, the row."""

    def __init__(self, store: PgLearningStore, embeddings: EmbeddingClient) -> None:
        """Wire a store to an embedding client of the schema's width.

        The width is checked here, at wiring time, rather than at the first
        write: a mismatch is a configuration error, and discovering it inside a
        background write path puts the message a long way from its cause.
        """
        require_matching_dimension(embeddings)
        self._store = store
        self._embeddings = embeddings

    async def store(self, learning: Learning) -> int:
        """Store a learning and persist an embedding of the row that resulted.

        The vector is computed from the **persisted** text, not from the text
        that was handed in. `PgLearningStore.store` deduplicates: a learning
        that overlaps an existing row's trigger keys increments that row's hit
        count and returns its id, leaving the existing text in place. Embedding
        the incoming text would then stamp the surviving row with a vector
        describing content it does not contain, so every later ranking would be
        about text no caller can see.

        An embedding failure is logged and swallowed. The row is already
        committed by then, and losing it because the vector could not be
        computed would trade degraded search for no memory at all -- it stays
        keyword-searchable, and `find_similar` skips it because its embedding
        is NULL.
        """
        learning_id = await self._store.store(learning)
        try:
            persisted = await self._store.text_of(learning_id)
            if persisted:
                vector = await self._embeddings.embed(persisted)
                await self._store.set_embedding(learning_id, vector)
        except Exception:
            logger.warning(
                "embedding failed for learning %s; it stays keyword-searchable", learning_id
            )
        return learning_id

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Similarity-ranked within scope, **merged with** keyword results.

        Not similarity-then-fallback. An early return on any similarity hit is
        wrong for the corpus this feature actually meets: a scope upgraded from
        before the column existed holds legacy rows with `embedding IS NULL`
        beside newly embedded ones, and one embedded row was enough to hide
        every legacy row for good -- including a query that matched a legacy
        row exactly. The same happens to any row whose embedding failed during
        `store`, which the docstring above promises stays keyword-searchable.

        Similarity leads because it is the better ranking when it applies;
        keyword results follow, de-duplicated by id, so the unembedded portion
        of the corpus remains reachable at every point of the migration.
        """
        found: list[Learning] = []
        try:
            vector = await self._embeddings.embed(user_text)
            found = await self._store.find_similar(
                vector, org_id=org_id, agent_id=agent_id, max_results=max_results
            )
        except Exception:
            logger.debug("query embedding failed; keyword results only")

        keyword = await self._store.find_relevant(
            user_text, agent_id=agent_id, org_id=org_id, max_results=max_results
        )

        seen = {learning.id for learning in found if learning.id is not None}
        for learning in keyword:
            if len(found) >= max_results:
                break
            if learning.id is not None and learning.id in seen:
                continue
            found.append(learning)
            if learning.id is not None:
                seen.add(learning.id)
        return found[:max_results]

    # The rest of `LearningStore` is pass-through. Spelled out rather than
    # delegated through `__getattr__`: the protocol is what the container type
    # checks against, and a dynamic forward satisfies the runtime while leaving
    # mypy unable to see any of it -- which is how a store ends up missing a
    # method nobody notices until a caller reaches for it.
    async def mark_used(self, learning_ids: list[int]) -> None:
        await self._store.mark_used(learning_ids)

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        await self._store.mark_outcome(learning_ids, success, org_id=org_id)

    async def check_auto_promotions(
        self, threshold: int = 5, *, org_id: str = ""
    ) -> list[Learning]:
        return await self._store.check_auto_promotions(threshold, org_id=org_id)

    async def get_promoted(
        self, task_type: str | None = None, *, org_id: str = ""
    ) -> list[Learning]:
        return await self._store.get_promoted(task_type, org_id=org_id)

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        return await self._store.list_all(org_id, limit)


__all__ = ["DurableHybridLearningStore"]
