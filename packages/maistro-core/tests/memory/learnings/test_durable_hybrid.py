"""The pass-through half of the durable hybrid store, and its merge bound (#188).

`DurableHybridLearningStore` wraps `PgLearningStore` so a scoped similarity read
composes with keyword search in one query. Most of `LearningStore` is not part
of that: it is forwarded verbatim, spelled out rather than routed through
`__getattr__` because the container type-checks against the protocol and a
dynamic forward satisfies the runtime while leaving mypy unable to see any of
it.

Spelled-out forwarding only helps if it is *correct*, and a hand-written
delegation is exactly the place a wrong argument order or a dropped keyword
hides — so each one is held to passing what it was given and returning what it
got back. The similarity path itself runs against a real PostgreSQL in
`tests/migrations/test_memory_embeddings.py`; these need no server.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore
from maistro.memory.vectors import EMBEDDING_DIMENSIONS
from maistro.types.memory import Learning


def _learning(learning_id: int, text: str = "do not do X") -> Learning:
    return Learning(id=learning_id, category="tool", learning=text, tool_name="bash")


class _Store:
    """Records every forwarded call, and answers with something identifiable."""

    def __init__(self, *, similar: list[Learning] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._similar = similar or []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def store(self, learning: Learning) -> int:
        self._record("store", learning)
        return 7

    async def text_of(self, learning_id: int) -> str:
        self._record("text_of", learning_id)
        return "persisted text"

    async def set_embedding(self, learning_id: int, vector: list[float]) -> None:
        self._record("set_embedding", learning_id, vector)

    async def find_similar(self, vector: list[float], **kwargs: Any) -> list[Learning]:
        self._record("find_similar", vector, **kwargs)
        return list(self._similar)

    async def find_relevant(self, user_text: str, **kwargs: Any) -> list[Learning]:
        self._record("find_relevant", user_text, **kwargs)
        return [_learning(1), _learning(2), _learning(3)]

    async def mark_used(self, learning_ids: list[int]) -> None:
        self._record("mark_used", learning_ids)

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        self._record("mark_outcome", learning_ids, success, org_id=org_id)

    async def check_auto_promotions(
        self, threshold: int = 5, *, org_id: str = ""
    ) -> list[Learning]:
        self._record("check_auto_promotions", threshold, org_id=org_id)
        return [_learning(11)]

    async def get_promoted(
        self, task_type: str | None = None, *, org_id: str = ""
    ) -> list[Learning]:
        self._record("get_promoted", task_type, org_id=org_id)
        return [_learning(12)]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        self._record("list_all", org_id, limit)
        return [_learning(13)]


class _Embeddings:
    dimension = EMBEDDING_DIMENSIONS

    async def embed(self, text: str) -> list[float]:
        return [0.0] * EMBEDDING_DIMENSIONS

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - unused
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]


@pytest.fixture
def wrapped() -> tuple[DurableHybridLearningStore, _Store]:
    store = _Store()
    return DurableHybridLearningStore(store, _Embeddings()), store  # type: ignore[arg-type]


# --- the forwarded half ----------------------------------------------------


async def test_mark_used_forwards_the_ids_it_was_given(wrapped) -> None:
    hybrid, store = wrapped

    await hybrid.mark_used([4, 5])

    assert store.calls == [("mark_used", ([4, 5],), {})]


async def test_mark_outcome_forwards_the_org_it_was_scoped_to(wrapped) -> None:
    """`org_id` is keyword-only downstream, and dropping it here would widen a
    scoped write into an unscoped one."""
    hybrid, store = wrapped

    await hybrid.mark_outcome([4], success=False, org_id="org-1")

    assert store.calls == [("mark_outcome", ([4], False), {"org_id": "org-1"})]


async def test_check_auto_promotions_forwards_and_returns(wrapped) -> None:
    hybrid, store = wrapped

    promoted = await hybrid.check_auto_promotions(3, org_id="org-1")

    assert store.calls == [("check_auto_promotions", (3,), {"org_id": "org-1"})]
    assert [item.id for item in promoted] == [11]


async def test_get_promoted_forwards_and_returns(wrapped) -> None:
    hybrid, store = wrapped

    promoted = await hybrid.get_promoted("build", org_id="org-1")

    assert store.calls == [("get_promoted", ("build",), {"org_id": "org-1"})]
    assert [item.id for item in promoted] == [12]


async def test_list_all_forwards_positionally_and_returns(wrapped) -> None:
    """Downstream takes both positionally; a keyword here would be a TypeError
    the type checker cannot see through a dynamic forward."""
    hybrid, store = wrapped

    listed = await hybrid.list_all("org-1", 5)

    assert store.calls == [("list_all", ("org-1", 5), {})]
    assert [item.id for item in listed] == [13]


# --- the merge bound -------------------------------------------------------


async def test_the_merge_stops_at_max_results() -> None:
    """Similarity leads and keyword follows, but the caller's bound holds.

    Without the bound the merged list is "similarity results plus every keyword
    result", which is up to twice what the caller asked for -- and the callers
    are prompt builders with a context budget.
    """
    store = _Store(similar=[_learning(90), _learning(91)])
    hybrid = DurableHybridLearningStore(store, _Embeddings())  # type: ignore[arg-type]

    found = await hybrid.find_relevant("why did it fail", max_results=3)

    # Two from similarity, then the loop takes one keyword result and breaks.
    assert [item.id for item in found] == [90, 91, 1]
