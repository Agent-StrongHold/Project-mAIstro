"""Tests for the learning lifecycle (issue #120 / M4-B4; ADR-015 + ADR-080 dynamics on learnings).

Five acceptance axes, each pinned behaviorally:
AC-1 contradiction/reinforcement evidence links to exact Runs/evaluations;
AC-2 confidence/ranking updates never erase prior versions/evidence;
AC-3 stale learnings can decay or be superseded;
AC-4 consolidation produces a new derived record with provenance to sources;
AC-5 conflicting active learnings are detectable and surfaced to retrieval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.learnings.lifecycle import (
    ConflictRecord,
    EvidenceLink,
    EvidenceLinkRequiredError,
    InactiveLearningError,
    InMemoryLearningLifecycle,
    LearningEvidence,
    LearningEvidenceKind,
    UnknownLearningError,
)
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning, MemoryScope

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _lr(
    keys: list[str],
    text: str,
    *,
    org: str = "org-1",
    tool: str = "shell",
    agent: str | None = "agent-1",
) -> Learning:
    return Learning(
        tool_name=tool,
        trigger_keys=keys,
        learning=text,
        org_id=org,
        agent_id=agent,
        scope=MemoryScope.AGENT,
    )


def _run_link(
    run: str = "run-100", node: str = "node-7", attempt: str = "attempt-2"
) -> EvidenceLink:
    return EvidenceLink(run_id=run, node_run_id=node, attempt_id=attempt)


class _Clock:
    """Deterministic clock the tests advance manually."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


def _lifecycle() -> tuple[InMemoryLearningLifecycle, InMemoryLearningStore, _Clock]:
    store = InMemoryLearningStore()
    clock = _Clock()
    return InMemoryLearningLifecycle(store, clock=clock), store, clock


def _kinds(lifecycle: InMemoryLearningLifecycle, learning_id: int) -> list[LearningEvidenceKind]:
    return [e.kind for e in lifecycle._evidence[learning_id]]


# ── AC-1: evidence links to exact Runs/evaluations ───────────────────────


class TestEvidenceLinks:
    async def test_reinforcement_evidence_names_the_exact_run(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        await lifecycle.reinforce([lid], link=_run_link(run="run-42", node="n1", attempt="a3"))

        (evidence,) = [
            e
            for e in await lifecycle.evidence_for(lid)
            if e.kind == LearningEvidenceKind.REINFORCED
        ]
        assert evidence.link.run_id == "run-42"
        assert evidence.link.node_run_id == "n1"
        assert evidence.link.attempt_id == "a3"

    async def test_reinforcement_evidence_can_name_an_evaluation_instead(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        await lifecycle.reinforce([lid], link=EvidenceLink(eval_id="eval-900"))

        (evidence,) = [
            e
            for e in await lifecycle.evidence_for(lid)
            if e.kind == LearningEvidenceKind.REINFORCED
        ]
        assert evidence.link.eval_id == "eval-900"
        assert evidence.link.run_id == ""

    async def test_contradiction_evidence_lands_on_both_sides_with_the_run(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "cache means never stale"))
        b = await lifecycle.observe(_lr(["ttl"], "cache always needs a ttl"))

        await lifecycle.record_contradiction(a, b, link=_run_link(run="run-77"))

        for side, other in ((a, b), (b, a)):
            (evidence,) = [
                e
                for e in await lifecycle.evidence_for(side)
                if e.kind == LearningEvidenceKind.CONTRADICTED
            ]
            assert evidence.link.run_id == "run-77"
            assert evidence.related_learning_id == other

    async def test_unattributed_reinforcement_is_refused(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        with pytest.raises(EvidenceLinkRequiredError):
            await lifecycle.reinforce([lid], link=EvidenceLink())
        # The refusal leaves no evidence and no revision behind: an
        # unattributable mutation of institutional knowledge never happened.
        assert _kinds(lifecycle, lid) == [LearningEvidenceKind.CREATED]
        assert len(await lifecycle.revisions_for(lid)) == 1

    async def test_supersession_and_consolidation_require_links(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["deploy"], "old rule"))
        b = await lifecycle.observe(_lr(["release"], "other rule"))
        with pytest.raises(EvidenceLinkRequiredError):
            await lifecycle.supersede(a, _lr(["deploy"], "new rule"), link=EvidenceLink())
        with pytest.raises(EvidenceLinkRequiredError):
            await lifecycle.consolidate(
                [a, b], _lr(["deploy", "release"], "merged"), link=EvidenceLink()
            )

    async def test_creation_evidence_adopts_the_producing_run(self) -> None:
        lifecycle, _, _ = _lifecycle()
        learning = _lr(["deploy"], "roll back before redeploy")
        learning.run_id = "run-9"
        learning.node_run_id = "node-2"
        learning.attempt_id = "attempt-1"

        lid = await lifecycle.observe(learning)

        (created,) = await lifecycle.evidence_for(lid)
        assert created.kind == LearningEvidenceKind.CREATED
        assert created.link.run_id == "run-9"


# ── AC-2: updates never erase prior versions/evidence ────────────────────


class TestHistoryPreserved:
    async def test_reinforce_preserves_the_prior_version(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        await lifecycle.reinforce([lid], link=_run_link())

        revisions = await lifecycle.revisions_for(lid)
        assert [r.revision for r in revisions] == [1, 2]
        assert revisions[0].snapshot.learning == "roll back before redeploy"
        assert (await lifecycle.standing(lid)).confidence == pytest.approx(0.55)
        # The live row is the same content — reinforcement moved confidence,
        # not content — but the revision chain now holds both states.
        assert (await lifecycle.current(lid)).learning == "roll back before redeploy"

    async def test_reinforce_then_weaken_keeps_the_full_chain_and_ledger(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))
        await lifecycle.reinforce([lid], link=_run_link(run="run-good"))
        await lifecycle.weaken([lid], link=_run_link(run="run-bad"), note="failed twice")

        kinds = _kinds(lifecycle, lid)
        assert kinds == [
            LearningEvidenceKind.CREATED,
            LearningEvidenceKind.REINFORCED,
            LearningEvidenceKind.WEAKENED,
        ]
        sequences = [e.sequence for e in await lifecycle.evidence_for(lid)]
        assert sequences == sorted(sequences) and len(set(sequences)) == 3
        revisions = await lifecycle.revisions_for(lid)
        assert [r.cause for r in revisions] == [
            LearningEvidenceKind.CREATED,
            LearningEvidenceKind.REINFORCED,
            LearningEvidenceKind.WEAKENED,
        ]
        standing = await lifecycle.standing(lid)
        assert standing.confidence == pytest.approx(0.5)

    async def test_supersede_keeps_the_old_record_reachable(self) -> None:
        lifecycle, store, _ = _lifecycle()
        old_id = await lifecycle.observe(_lr(["deploy"], "always force-push main"))

        _, replacement = await lifecycle.supersede(
            old_id, _lr(["deploy"], "never force-push shared branches"), link=_run_link(run="run-5")
        )

        every = await store.list_all(org_id="org-1")
        texts = sorted(item.learning for item in every)
        assert texts == ["always force-push main", "never force-push shared branches"]
        old = await lifecycle.current(old_id)
        assert old.status == "superseded"
        assert old.learning == "always force-push main"
        assert replacement.status == "active"

    async def test_retirement_preserves_the_record_and_records_the_reason(self) -> None:
        lifecycle, store, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        await lifecycle.retire([lid], reason="context shifted: monorepo split")

        assert (await lifecycle.current(lid)).status == "retired"
        assert [item.learning for item in await store.list_all(org_id="org-1")] == [
            "roll back before redeploy"
        ]
        (retired,) = [
            e for e in await lifecycle.evidence_for(lid) if e.kind == LearningEvidenceKind.RETIRED
        ]
        assert retired.note == "context shifted: monorepo split"


# ── AC-3: decay and supersession ─────────────────────────────────────────


class TestDecayAndSupersession:
    async def test_stale_learning_decays_with_silence(self) -> None:
        lifecycle, _, clock = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))
        clock.advance(hours=10)

        sweep = await lifecycle.decay()

        assert (sweep.scanned, sweep.decayed, sweep.retired) == (1, 1, 0)
        assert (await lifecycle.standing(lid)).confidence == pytest.approx(0.4)
        (decayed,) = [
            e for e in await lifecycle.evidence_for(lid) if e.kind == LearningEvidenceKind.DECAYED
        ]
        assert "10.00h" in decayed.note

    async def test_fresh_learning_does_not_decay_and_sweeps_do_not_double_charge(self) -> None:
        lifecycle, _, clock = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))

        await lifecycle.decay()  # no silence yet
        await lifecycle.decay()  # still the same instant
        assert (await lifecycle.standing(lid)).confidence == pytest.approx(0.5)

        clock.advance(hours=5)
        await lifecycle.decay()
        assert (await lifecycle.standing(lid)).confidence == pytest.approx(0.45)

    async def test_reinforcement_refreshes_the_decay_clock(self) -> None:
        lifecycle, _, clock = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))
        clock.advance(hours=8)
        await lifecycle.decay()
        stale = (await lifecycle.standing(lid)).confidence

        clock.advance(minutes=30)
        await lifecycle.reinforce([lid], link=_run_link(run="run-good"))
        clock.advance(hours=8)
        await lifecycle.decay()

        refreshed = (await lifecycle.standing(lid)).confidence
        assert refreshed == pytest.approx(stale + 0.05 - 0.08)

    async def test_decay_respects_the_floor_and_can_retire(self) -> None:
        store = InMemoryLearningStore()
        clock = _Clock()
        lifecycle = InMemoryLearningLifecycle(
            store, decay_per_hour=0.004, decay_floor=0.05, retire_below=0.12, clock=clock
        )
        survivor = await lifecycle.observe(_lr(["deploy"], "survivor"))
        gone = await lifecycle.observe(_lr(["cache"], "doomed"))
        await lifecycle.reinforce([survivor], link=_run_link(run="run-1"))  # 0.55
        clock.advance(hours=100)

        sweep = await lifecycle.decay()

        assert (sweep.scanned, sweep.decayed, sweep.retired) == (2, 2, 1)
        # 0.55 - 0.4 lands above the floor, so the quiet lesson survives with
        # exactly its decayed confidence; the floor itself is pinned below.
        assert (await lifecycle.standing(survivor)).confidence == pytest.approx(0.15)
        assert (await lifecycle.current(survivor)).status == "active"
        assert (await lifecycle.current(gone)).status == "retired"
        assert _kinds(lifecycle, gone)[-1] == LearningEvidenceKind.RETIRED

    async def test_supersede_drops_the_old_side_from_retrieval_only(self) -> None:
        lifecycle, store, _ = _lifecycle()
        old_id = await lifecycle.observe(_lr(["deploy"], "always force-push main"))
        await lifecycle.supersede(
            old_id, _lr(["deploy", "push"], "never force-push shared branches"), link=_run_link()
        )

        result = await lifecycle.find_relevant("force push the branch", org_id="org-1")
        assert [lr.learning for lr in result.learnings] == ["never force-push shared branches"]
        # ...while the admin view keeps the superseded statement.
        assert len(await store.list_all(org_id="org-1")) == 2

    async def test_supersede_refuses_an_inactive_learning(self) -> None:
        lifecycle, _, _ = _lifecycle()
        old_id = await lifecycle.observe(_lr(["deploy"], "old"))
        await lifecycle.retire([old_id], reason="done")
        with pytest.raises(InactiveLearningError):
            await lifecycle.supersede(old_id, _lr(["deploy"], "new"), link=_run_link())


# ── AC-4: consolidation with provenance to sources ───────────────────────


class TestConsolidation:
    async def test_consolidation_creates_a_derived_record_with_provenance(self) -> None:
        lifecycle, store, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))
        b = await lifecycle.observe(_lr(["revert"], "revert bad deploys fast"))

        merged, record = await lifecycle.consolidate(
            [a, b],
            _lr(["deploy", "revert"], "bad deploys: revert fast, roll back before redeploy"),
            link=_run_link(run="run-cc"),
        )

        assert record.derived_id == merged.id
        assert record.source_ids == (a, b)
        assert record.link.run_id == "run-cc"
        assert sorted(item.learning for item in await store.list_all(org_id="org-1")) == sorted(
            [
                "roll back before redeploy",
                "revert bad deploys fast",
                "bad deploys: revert fast, roll back before redeploy",
            ]
        )
        assert merged.status == "active"
        derived_evidence = await lifecycle.evidence_for(merged.id)
        assert derived_evidence[0].kind == LearningEvidenceKind.CONSOLIDATED

    async def test_consolidation_preserves_and_deactivates_sources(self) -> None:
        lifecycle, store, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["deploy"], "roll back before redeploy"))
        b = await lifecycle.observe(_lr(["revert"], "revert bad deploys fast"))

        await lifecycle.consolidate(
            [a, b], _lr(["deploy", "revert"], "combined deploy-revert lesson"), link=_run_link()
        )

        assert (await lifecycle.current(a)).status == "consolidated"
        assert (await lifecycle.current(b)).status == "consolidated"
        # Sources kept, not deleted: three rows remain in the admin view.
        assert len(await store.list_all(org_id="org-1")) == 3
        # Neither source is retrievable any more, the derived record is.
        result = await lifecycle.find_relevant("deploy revert", org_id="org-1")
        assert [lr.learning for lr in result.learnings] == ["combined deploy-revert lesson"]

    async def test_consolidation_needs_two_distinct_sources(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["deploy"], "one"))
        with pytest.raises(ValueError, match="at least two"):
            await lifecycle.consolidate([a, a], _lr(["deploy"], "merged"), link=_run_link())

    async def test_consolidation_does_not_dedup_into_a_source(self) -> None:
        """The merged record must be a new row even when it overlaps its sources' keys."""
        lifecycle, store, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["deploy", "rollback"], "rule one"))
        b = await lifecycle.observe(_lr(["deploy", "revert"], "rule two"))

        merged, record = await lifecycle.consolidate(
            [a, b], _lr(["deploy", "rollback", "revert"], "combined"), link=_run_link()
        )

        assert merged.id not in (a, b)
        assert record.derived_id == merged.id
        assert len(await store.list_all(org_id="org-1")) == 3


# ── AC-5: conflicts detectable and surfaced ──────────────────────────────


class TestConflictDetectionAndSurfacing:
    async def test_contradicting_active_learnings_are_detectable(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "cache is always safe"))
        b = await lifecycle.observe(_lr(["ttl"], "cache needs a ttl"))
        other = await lifecycle.observe(_lr(["deploy"], "unrelated"))

        records = await lifecycle.find_conflicts()
        assert [r.a_id for r in records] == []  # nothing yet

        record = await lifecycle.record_contradiction(a, b, link=_run_link(run="run-detector"))

        records = await lifecycle.find_conflicts()
        assert len(records) == 1
        assert records[0].conflict_id == record.conflict_id
        assert {records[0].a_id, records[0].b_id} == {a, b}
        # An unrelated third learning is not dragged in.
        assert other not in (records[0].a_id, records[0].b_id)

    async def test_both_sides_stay_active_but_weakened(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "one"))
        b = await lifecycle.observe(_lr(["ttl"], "two"))

        await lifecycle.record_contradiction(a, b, link=_run_link())

        assert (await lifecycle.current(a)).status == "active"
        assert (await lifecycle.current(b)).status == "active"
        assert (await lifecycle.standing(a)).confidence == pytest.approx(0.45)
        assert (await lifecycle.standing(b)).confidence == pytest.approx(0.45)

    async def test_re_registering_a_pair_keeps_one_record_but_new_evidence(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "one"))
        b = await lifecycle.observe(_lr(["ttl"], "two"))
        first = await lifecycle.record_contradiction(a, b, link=_run_link(run="run-1"))

        second = await lifecycle.record_contradiction(a, b, link=_run_link(run="run-2"))

        assert second.conflict_id == first.conflict_id
        assert (await lifecycle.standing(a)).confidence == pytest.approx(0.4)
        contradicted = [
            e
            for e in await lifecycle.evidence_for(a)
            if e.kind == LearningEvidenceKind.CONTRADICTED
        ]
        assert [e.link.run_id for e in contradicted] == ["run-1", "run-2"]

    async def test_resolution_removes_pair_from_detection_until_included(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "one"))
        b = await lifecycle.observe(_lr(["ttl"], "two"))
        record = await lifecycle.record_contradiction(a, b, link=_run_link())

        await lifecycle.resolve_conflict(record.conflict_id, resolution="keep b, supersede a")

        assert await lifecycle.find_conflicts() == []
        assert len(await lifecycle.find_conflicts(include_resolved=True)) == 1
        with pytest.raises(ValueError, match="resolution"):
            await lifecycle.resolve_conflict(record.conflict_id, resolution="  ")
        with pytest.raises(UnknownLearningError):
            await lifecycle.resolve_conflict("missing", resolution="x")

    async def test_a_superseded_side_drops_out_of_conflict_detection(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache"], "one"))
        b = await lifecycle.observe(_lr(["ttl"], "two"))
        await lifecycle.record_contradiction(a, b, link=_run_link())
        await lifecycle.resolve_conflict(
            (await lifecycle.find_conflicts())[0].conflict_id, resolution="a is outdated"
        )
        await lifecycle.supersede(a, _lr(["cache"], "cache needs explicit ttl"), link=_run_link())

        assert await lifecycle.find_conflicts() == []

    async def test_retrieval_surfaces_the_conflict_with_both_sides(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache", "http"], "cache is always safe"))
        b = await lifecycle.observe(_lr(["cache", "ttl"], "cache needs a ttl"))
        await lifecycle.record_contradiction(a, b, link=_run_link())

        result = await lifecycle.find_relevant("fix the http cache ttl", org_id="org-1")

        assert len(result.learnings) == 2
        assert len(result.conflicts) == 1
        surfaced = result.conflicts[0]
        assert {surfaced.a.id, surfaced.b.id} == {a, b}

    async def test_retrieval_surfaces_a_conflict_whose_other_side_was_not_retrieved(self) -> None:
        lifecycle, _, _ = _lifecycle()
        a = await lifecycle.observe(_lr(["cache", "http"], "cache is always safe"))
        b = await lifecycle.observe(_lr(["totally-other-key"], "cache needs a ttl"))
        await lifecycle.record_contradiction(a, b, link=_run_link())

        result = await lifecycle.find_relevant("the http cache", org_id="org-1")

        assert [lr.id for lr in result.learnings] == [a]
        assert len(result.conflicts) == 1
        assert result.conflicts[0].b.learning == "cache needs a ttl"

    async def test_retrieval_reranks_equal_relevance_by_confidence(self) -> None:
        lifecycle, _, _ = _lifecycle()
        weak = await lifecycle.observe(_lr(["deploy"], "weak version"))
        strong = await lifecycle.observe(_lr(["cache"], "strong version"))
        await lifecycle.weaken([weak], link=_run_link(run="run-bad"), delta=0.3)
        await lifecycle.reinforce([strong], link=_run_link(run="run-good"))

        result = await lifecycle.find_relevant("deploy the cache", org_id="org-1")

        assert [lr.learning for lr in result.learnings] == ["strong version", "weak version"]


# ── lifecycle bookkeeping ────────────────────────────────────────────────


class TestBookkeeping:
    async def test_unknown_learning_is_refused(self) -> None:
        lifecycle, _, _ = _lifecycle()
        with pytest.raises(UnknownLearningError):
            await lifecycle.reinforce([404], link=_run_link())
        with pytest.raises(UnknownLearningError):
            await lifecycle.current(404)
        with pytest.raises(UnknownLearningError):
            await lifecycle.standing(404)

    async def test_retire_requires_a_reason(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "x"))
        with pytest.raises(ValueError, match="reason"):
            await lifecycle.retire([lid], reason="  ")

    async def test_self_contradiction_is_refused(self) -> None:
        lifecycle, _, _ = _lifecycle()
        lid = await lifecycle.observe(_lr(["deploy"], "x"))
        with pytest.raises(ValueError, match="itself"):
            await lifecycle.record_contradiction(lid, lid, link=_run_link())

    async def test_conflict_record_refuses_an_unattributed_detection(self) -> None:
        with pytest.raises(EvidenceLinkRequiredError):
            ConflictRecord(conflict_id="c1", a_id=1, b_id=2, detected_at=T0, link=EvidenceLink())

    async def test_naive_timestamps_are_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            LearningEvidence(
                sequence=1,
                learning_id=1,
                kind=LearningEvidenceKind.DECAYED,
                at=datetime(2026, 9, 1, 12),
            )
