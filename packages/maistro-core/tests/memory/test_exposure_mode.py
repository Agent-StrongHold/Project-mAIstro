"""Tests for the memory exposure mode gating primitive (SPEC-249 / ADR-057)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.memory.exposure import (
    Actor,
    BlockExposure,
    MemoryExposureMode,
    MemoryWriteDenied,
    enforce_promote,
    enforce_write,
)


class TestEnforceWrite:
    def test_system_managed_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT)

    def test_system_managed_allows_system(self) -> None:
        assert enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.SYSTEM) is None

    def test_agent_managed_allows_agent(self) -> None:
        assert enforce_write(MemoryExposureMode.AGENT_MANAGED, Actor.AGENT) is None

    def test_agent_managed_allows_system(self) -> None:
        assert enforce_write(MemoryExposureMode.AGENT_MANAGED, Actor.SYSTEM) is None

    def test_hybrid_system_managed_tag_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_write(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.SYSTEM_MANAGED,
            )

    def test_hybrid_agent_managed_tag_allows_agent(self) -> None:
        assert (
            enforce_write(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.AGENT_MANAGED,
            )
            is None
        )

    def test_hybrid_without_block_exposure_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            enforce_write(MemoryExposureMode.HYBRID, Actor.AGENT)

    def test_denial_carries_scope_actor_mode_reason(self) -> None:
        with pytest.raises(MemoryWriteDenied) as exc_info:
            enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT, scope="agent")
        denied = exc_info.value
        assert denied.scope == "agent"
        assert denied.actor == Actor.AGENT
        assert denied.mode == MemoryExposureMode.SYSTEM_MANAGED
        assert denied.reason


class TestEnforcePromote:
    def test_system_managed_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_promote(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT)

    def test_system_managed_allows_system(self) -> None:
        assert enforce_promote(MemoryExposureMode.SYSTEM_MANAGED, Actor.SYSTEM) is None

    def test_agent_managed_allows_agent(self) -> None:
        assert enforce_promote(MemoryExposureMode.AGENT_MANAGED, Actor.AGENT) is None

    def test_hybrid_system_managed_tag_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_promote(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.SYSTEM_MANAGED,
            )

    def test_hybrid_agent_managed_tag_allows_agent(self) -> None:
        assert (
            enforce_promote(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.AGENT_MANAGED,
            )
            is None
        )

    def test_hybrid_without_block_exposure_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            enforce_promote(MemoryExposureMode.HYBRID, Actor.AGENT)


@given(
    mode=st.sampled_from(MemoryExposureMode),
    block_exposure=st.one_of(st.none(), st.sampled_from(BlockExposure)),
)
def test_system_actor_never_denied(
    mode: MemoryExposureMode, block_exposure: BlockExposure | None
) -> None:
    if mode == MemoryExposureMode.HYBRID and block_exposure is None:
        block_exposure = BlockExposure.SYSTEM_MANAGED
    assert enforce_write(mode, Actor.SYSTEM, block_exposure=block_exposure) is None
    assert enforce_promote(mode, Actor.SYSTEM, block_exposure=block_exposure) is None


# ── store-boundary wiring (SPEC-062126-6a31, #390) ───────────────────────────
#
# The primitive above only proves the matrix. These classes prove the gate is
# *reachable* in every production memory store: each real store class,
# constructed bare (no declared mode), refuses its first mutation with
# MemoryUndeclaredModeError — which is exactly the fail-closed contract, and
# works without a database because the gate precedes all I/O.


from maistro.memory.episodic.store import InMemoryEpisodicStore  # noqa: E402
from maistro.memory.exposure import MemoryUndeclaredModeError  # noqa: E402
from maistro.memory.learnings.store import InMemoryLearningStore  # noqa: E402
from maistro.memory.mutations import InMemorySkillMutationStore  # noqa: E402
from maistro.memory.outcomes import InMemoryOutcomeStore  # noqa: E402
from maistro.persistence.pg_episodic import PgEpisodicStore  # noqa: E402
from maistro.persistence.pg_learnings import PgLearningStore  # noqa: E402
from maistro.persistence.pg_outcomes import PgOutcomeStore  # noqa: E402
from maistro.persistence.sqlite_episodic import SqliteEpisodicStore  # noqa: E402
from maistro.persistence.sqlite_learnings import SqliteLearningStore  # noqa: E402
from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore  # noqa: E402
from maistro.types.memory import (  # noqa: E402
    EpisodicMemory,
    Learning,
    LearningStage,
    Outcome,
    SkillMutation,
)


class TestReachabilityAtStoreBoundary:
    """Every production memory store fails closed when no mode is declared."""

    def test_in_memory_learning_store(self) -> None:
        store = InMemoryLearningStore()
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(Learning(), actor=Actor.SYSTEM))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.check_auto_promotions(actor=Actor.SYSTEM))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.supersede(1, Learning(learning="x")))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.consolidate())
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.advance_stage(1, to_stage=LearningStage.LEARNING, actor="x"))

    def test_in_memory_episodic_store(self) -> None:
        store = InMemoryEpisodicStore()
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(EpisodicMemory(), actor=Actor.SYSTEM))

    def test_in_memory_outcome_store(self) -> None:
        store = InMemoryOutcomeStore()
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.record(Outcome(), actor=Actor.SYSTEM))

    def test_in_memory_skill_mutation_store(self) -> None:
        store = InMemorySkillMutationStore()
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.record(SkillMutation(), actor=Actor.SYSTEM))

    def test_pg_learning_store(self) -> None:
        store = PgLearningStore(pool=None)  # type: ignore[arg-type]
        # The gate precedes every I/O touch, so an unwired pool never matters.
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(Learning(), actor=Actor.SYSTEM))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.check_auto_promotions(actor=Actor.SYSTEM))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.advance_stage(1, to_stage=LearningStage.LEARNING, actor="x"))

    def test_sqlite_learning_store(self) -> None:
        store = SqliteLearningStore(conn=None)  # type: ignore[arg-type]
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(Learning(), actor=Actor.SYSTEM))
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.advance_stage(1, to_stage=LearningStage.LEARNING, actor="x"))

    def test_pg_episodic_store(self) -> None:
        store = PgEpisodicStore(pool=None)  # type: ignore[arg-type]
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(EpisodicMemory(), actor=Actor.SYSTEM))

    def test_sqlite_episodic_store(self) -> None:
        store = SqliteEpisodicStore(conn=None)  # type: ignore[arg-type]
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.store(EpisodicMemory(), actor=Actor.SYSTEM))

    def test_pg_outcome_store(self) -> None:
        store = PgOutcomeStore(pool=None)  # type: ignore[arg-type]
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.record(Outcome(), actor=Actor.SYSTEM))

    def test_sqlite_outcome_store(self) -> None:
        store = SqliteOutcomeStore(conn=None)  # type: ignore[arg-type]
        with pytest.raises(MemoryUndeclaredModeError):
            asyncio_run(store.record(Outcome(), actor=Actor.SYSTEM))


class TestTwoActorInMemoryStores:
    """The ADR-057 matrix exercised through real store methods, not the gate."""

    def test_agent_write_denied_under_system_managed_and_state_untouched(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.store(Learning(learning="x"), actor=Actor.AGENT))
        assert store._learnings == []

    def test_agent_promotion_denied_under_system_managed(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.check_auto_promotions(actor=Actor.AGENT))

    def test_agent_write_allowed_under_agent_managed(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        learning_id = asyncio_run(store.store(Learning(learning="x"), actor=Actor.AGENT))
        assert learning_id == 1

    def test_episodic_agent_write_denied_under_system_managed(self) -> None:
        store = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.store(EpisodicMemory(content="x"), actor=Actor.AGENT))
        assert store._memories == []

    def test_episodic_agent_write_allowed_under_agent_managed(self) -> None:
        store = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        memory_id = asyncio_run(store.store(EpisodicMemory(content="x"), actor=Actor.AGENT))
        assert memory_id

    def test_outcome_agent_record_denied_under_system_managed(self) -> None:
        store = InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.record(Outcome(), actor=Actor.AGENT))
        assert store._outcomes == []

    def test_skill_mutation_agent_record_denied_under_system_managed(self) -> None:
        store = InMemorySkillMutationStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.record(SkillMutation(), actor=Actor.AGENT))
        assert store._mutations == []

    def test_hybrid_without_block_tags_fails_closed_for_agent_writes(self) -> None:
        # No durable memory block type carries a per-block exposure tag yet, so
        # a declared HYBRID store denies agent writes at the gate (the gate's
        # ValueError for a missing tag) instead of silently allowing them.
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.HYBRID)
        with pytest.raises(ValueError, match="HYBRID mode requires block_exposure"):
            asyncio_run(store.store(Learning(learning="x"), actor=Actor.AGENT))
        assert store._learnings == []

    def test_agent_supersede_denied_under_system_managed_leaves_no_partial_state(self) -> None:
        """A denied supersede retires nothing and stores nothing (#390).

        The pre-gate implementation retired the old row *before* the gated
        store() call, so a denial left the old row superseded with no
        replacement — exactly the partial durable state ADR-057 forbids.
        """
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        old_id = asyncio_run(store.store(Learning(learning="old"), actor=Actor.SYSTEM))
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.supersede(old_id, Learning(learning="new"), actor=Actor.AGENT))
        assert len(store._learnings) == 1
        assert store._learnings[0].id == old_id
        assert store._learnings[0].status == "active"
        assert store._learnings[0].learning == "old"

    def test_system_supersede_under_system_managed_carries_one_principal(self) -> None:
        """The gate's principal is the one the inner store() call runs under."""
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        old_id = asyncio_run(store.store(Learning(learning="old"), actor=Actor.SYSTEM))
        new_id = asyncio_run(store.supersede(old_id, Learning(learning="new"), actor=Actor.SYSTEM))
        assert new_id != old_id
        assert asyncio_run(store.get(old_id)).status == "superseded"
        assert asyncio_run(store.get(new_id)).status == "active"

    def test_agent_consolidate_denied_under_system_managed_merges_nothing(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        # Disjoint trigger keys so the write-path dedup probe keeps both rows
        # alive: the denial, not a dedup fold, must be why nothing merged.
        first = asyncio_run(
            store.store(Learning(learning="a", trigger_keys=["deploy"]), actor=Actor.SYSTEM)
        )
        second = asyncio_run(
            store.store(Learning(learning="b", trigger_keys=["rollback"]), actor=Actor.SYSTEM)
        )
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.consolidate(org_id="", actor=Actor.AGENT))
        assert [lr.id for lr in store._learnings] == [first, second]
        assert all(lr.status == "active" for lr in store._learnings)

    def test_agent_advance_stage_denied_under_system_managed(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        lid = asyncio_run(store.store(Learning(learning="x"), actor=Actor.SYSTEM))
        with pytest.raises(MemoryWriteDenied):
            asyncio_run(store.advance_stage(lid, to_stage=LearningStage.LEARNING, actor="planner"))
        assert store._learnings[0].stage is LearningStage.MEMORY
        assert store._stage_history == []

    def test_system_advance_stage_allowed_under_system_managed(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.SYSTEM_MANAGED)
        lid = asyncio_run(store.store(Learning(learning="x"), actor=Actor.SYSTEM))
        learning = asyncio_run(
            store.advance_stage(
                lid, to_stage=LearningStage.LEARNING, actor="curator", authority=Actor.SYSTEM
            )
        )
        assert learning.stage is LearningStage.LEARNING
        assert store._stage_history[0].actor == "curator"


class TestGovernanceNoProductIdentityBranch:
    """ADR-057: no engine code picks an exposure mode from product identity.

    Any line in the memory module or the memory stores that names a product is
    a comment at most; the same line referencing the mode decision would be the
    forbidden branch (ADR-019/ADR-030).
    """

    PRODUCT_TOKENS = ("turing", "stronghold", "conductor", "canvas", "davinci", "da vinci")
    DECISION_SYMBOLS = (
        "MemoryExposureMode",
        "MemoryWriteDenied",
        "enforce_write",
        "enforce_promote",
        "require_write_authority",
        "exposure_mode",
        "_agent_allowed",
    )

    def _sources(self) -> dict[str, str]:
        import pathlib

        import maistro.memory as maistro_memory
        import maistro.persistence as maistro_persistence

        root = pathlib.Path(maistro_memory.__file__).parent
        sources: dict[str, str] = {}
        for path in sorted(root.rglob("*.py")):
            sources[str(path)] = path.read_text()
        persistence = pathlib.Path(maistro_persistence.__file__).parent
        for name in (
            "pg_learnings.py",
            "sqlite_learnings.py",
            "pg_episodic.py",
            "sqlite_episodic.py",
            "pg_outcomes.py",
            "sqlite_outcomes.py",
        ):
            path = persistence / name
            sources[str(path)] = path.read_text()
        return sources

    def test_no_product_line_touches_the_mode_decision(self) -> None:
        for path, text in self._sources().items():
            for number, line in enumerate(text.splitlines(), start=1):
                lowered = line.lower()
                if not any(token in lowered for token in self.PRODUCT_TOKENS):
                    continue
                if "__pycache__" in path:
                    continue
                hits = [s for s in self.DECISION_SYMBOLS if s in line]
                assert not hits, (
                    f"{path}:{number} names a product and the exposure decision "
                    f"({', '.join(hits)}); engine code must not branch on "
                    "product identity (ADR-057 governance)."
                )


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)
