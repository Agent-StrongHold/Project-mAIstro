"""Store-level lifecycle operations (ADR-092, M4-B #120).

The rules live in lifecycle.py; these tests pin how InMemoryLearningStore
applies them to real rows, including the scope rules the other store methods
follow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.protocols.memory import (
    IneffectiveLearningSource,
    LearningLifecycleStore,
    LearningStore,
)
from maistro.types.memory import Learning

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _lr(**overrides: object) -> Learning:
    keys = overrides.pop("keys", None)
    kwargs: dict[str, object] = {
        "trigger_keys": keys or ["deploy"],
        "learning": "do X not Y",
        "org_id": "org-1",
    }
    kwargs.update(overrides)
    return Learning(**kwargs)  # type: ignore[arg-type]


class TestProtocolConformance:
    def test_in_memory_store_runs_the_lifecycle(self) -> None:
        store = InMemoryLearningStore()
        assert isinstance(store, LearningStore)
        assert isinstance(store, LearningLifecycleStore)
        assert isinstance(store, IneffectiveLearningSource)

    def test_bare_class_conforms_to_nothing(self) -> None:
        class Stub:
            pass

        assert not isinstance(Stub(), LearningLifecycleStore)
        assert not isinstance(Stub(), IneffectiveLearningSource)


class TestPointRead:
    async def test_get_found_and_missing(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(_lr())
        assert (await store.get(lid)) is not None
        assert await store.get(999) is None

    async def test_get_org_narrows_when_given(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(_lr(org_id="org-1"))
        assert await store.get(lid, org_id="org-2") is None
        assert await store.get(lid, org_id="org-1") is not None


class TestReinforceContradict:
    async def test_reinforce_missing_id_is_none(self) -> None:
        store = InMemoryLearningStore()
        assert await store.reinforce(42) is None

    async def test_reinforce_and_contradict_move_the_row(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(_lr())
        before = await store.get(lid)
        assert before is not None
        await store.reinforce(lid, org_id="org-1")
        await store.contradict(lid, org_id="org-1")
        after = await store.get(lid)
        assert after is not None
        assert after.reinforcement_count == 1
        assert after.contradiction_count == 1
        assert after.confidence == pytest.approx(before.confidence)

    async def test_contradict_respects_org_scope(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(_lr(org_id="org-1"))
        assert await store.contradict(lid, org_id="org-2") is None
        row = await store.get(lid)
        assert row is not None
        assert row.contradiction_count == 0


class TestSupersede:
    async def test_supersede_unknown_id_raises(self) -> None:
        store = InMemoryLearningStore()
        with pytest.raises(KeyError):
            await store.supersede(42, _lr())

    async def test_supersede_replaces_without_folding_into_the_old_row(self) -> None:
        # The replacement overlaps the old row's keys; dedup must not fold it
        # back into the row being replaced (dedup probes active rows only, and
        # the old row is retired first).
        store = InMemoryLearningStore()
        old_id = await store.store(_lr(keys=["deploy", "prod"]))
        new_id = await store.supersede(
            old_id,
            _lr(keys=["deploy", "prod", "verify"], learning="v2: also verify"),
        )
        assert new_id != old_id
        old = await store.get(old_id)
        new = await store.get(new_id)
        assert old is not None and new is not None
        assert old.status == "superseded"
        assert old.superseded_by == new_id
        assert new.supersedes == old_id
        assert new.status == "active"
        assert new.learning == "v2: also verify"

    async def test_superseded_rows_stay_readable(self) -> None:
        # Institutional knowledge is retained, never deleted.
        store = InMemoryLearningStore()
        old_id = await store.store(_lr(learning="old belief"))
        await store.supersede(old_id, _lr(learning="new belief"))
        old = await store.get(old_id)
        assert old is not None
        assert old.learning == "old belief"


class TestApplyDecay:
    async def test_decay_sweep_moves_aged_rows_and_counts_them(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(created_at=NOW - timedelta(days=30)))
        assert await store.apply_decay(now=NOW) == 1

    async def test_fresh_rows_do_not_count_as_decayed(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(created_at=NOW))
        assert await store.apply_decay(now=NOW) == 0

    async def test_terminal_rows_do_not_decay(self) -> None:
        store = InMemoryLearningStore()
        old_id = await store.store(_lr(created_at=NOW - timedelta(days=30)))
        new_id = await store.supersede(old_id, _lr(created_at=NOW - timedelta(days=30)))
        superseded = await store.get(old_id)
        assert superseded is not None
        frozen = superseded.confidence
        assert await store.apply_decay(now=NOW + timedelta(days=365)) >= 1
        assert superseded.confidence == frozen
        # ...while its replacement does decay.
        new = await store.get(new_id)
        assert new is not None
        assert new.confidence < 0.5


class TestConsolidate:
    # Write-time dedup (ADR-015) already folds overlapping rows, so the rows a
    # consolidation sweep actually finds are drifted ones -- rows whose trigger
    # keys changed after storing. The tests below create that state through the
    # public API (mutate keys on the returned rows) rather than reaching into
    # store internals.

    async def test_merges_same_axes_overlapping_rows(self) -> None:
        store = InMemoryLearningStore()
        a_id = await store.store(_lr(keys=["deploy"], learning="a", success_after_use=2))
        b_id = await store.store(
            _lr(keys=["rollback"], learning="b", failure_after_use=3, hit_count=4)
        )
        # Later enrichment widens both key sets into overlap.
        drifted_a = await store.get(a_id)
        drifted_b = await store.get(b_id)
        assert drifted_a is not None and drifted_b is not None
        drifted_a.trigger_keys = ["deploy", "prod"]
        drifted_b.trigger_keys = ["deploy", "prod", "rollback"]

        survivors = await store.consolidate()
        assert len(survivors) == 1
        survivor = survivors[0]
        assert survivor.id == a_id  # earliest row survives
        assert survivor.trigger_keys == ["deploy", "prod", "rollback"]
        assert survivor.success_after_use == 2
        assert survivor.failure_after_use == 3
        assert survivor.hit_count == 4
        absorbed = await store.get(b_id)
        assert absorbed is not None
        assert absorbed.status == "consolidated"
        assert absorbed.superseded_by == a_id

    async def test_does_not_merge_below_overlap_threshold(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["a", "b"]))
        await store.store(_lr(keys=["b", "c"]))  # 1/3 overlap < 0.5
        assert len(await store.consolidate()) == 2

    async def test_does_not_merge_across_orgs_or_tools(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["deploy", "prod"], org_id="org-1"))
        await store.store(_lr(keys=["deploy", "prod"], org_id="org-2"))
        await store.store(_lr(keys=["deploy", "prod"], tool_name="other"))
        assert len(await store.consolidate()) == 3

    async def test_org_narrows_the_sweep_and_blank_sweeps_all(self) -> None:
        store = InMemoryLearningStore()
        one_id = await store.store(_lr(keys=["deploy"], org_id="org-1"))
        two_id = await store.store(_lr(keys=["prod"], org_id="org-1"))
        await store.store(_lr(keys=["deploy"], org_id="org-2"))
        drifted_one = await store.get(one_id)
        drifted_two = await store.get(two_id)
        assert drifted_one is not None and drifted_two is not None
        drifted_one.trigger_keys = ["deploy", "prod"]
        drifted_two.trigger_keys = ["deploy", "prod"]

        # Scoped sweep: org-1's drifted pair merges, org-2's row is untouched.
        assert len(await store.consolidate(org_id="org-1")) == 1
        all_rows = await store.list_all()
        statuses = sorted(r.status for r in all_rows)
        assert statuses == ["active", "active", "consolidated"]
        # Blank org sweeps every org (admin semantics, like list_all); the
        # already-consolidated pair contributes only its survivor.
        assert len(await store.consolidate()) == 2

    async def test_consolidated_rows_are_not_remerged(self) -> None:
        store = InMemoryLearningStore()
        a_id = await store.store(_lr(keys=["deploy"]))
        b_id = await store.store(_lr(keys=["prod"]))
        drifted_a = await store.get(a_id)
        drifted_b = await store.get(b_id)
        assert drifted_a is not None and drifted_b is not None
        drifted_a.trigger_keys = ["deploy", "prod"]
        drifted_b.trigger_keys = ["deploy", "prod"]

        assert len(await store.consolidate()) == 1
        # Idempotent: a second sweep finds no active overlap to merge.
        assert len(await store.consolidate()) == 1
