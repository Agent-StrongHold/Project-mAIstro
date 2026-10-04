"""Applicability, epistemic type and provenance survival on learnings (M4-B3).

A reusable learning is a context-dependent claim, not a universal truth: it
carries `works_when` / `avoid_in`, an explicit `EpistemicType` usable by
retrieval ranking, and evidence that must survive consolidation and rewording.
The CoinSwarm wisdom import (`wisdom.learning_from_wisdom`) is covered here
too — it is the canonical REPORTED producer of these fields.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.memory.learnings.evidence import merge_applicability
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.learnings.wisdom import learning_from_wisdom
from maistro.observability.correlation import bind_execution_context
from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import EpistemicType, Learning, MemoryScope


@pytest.mark.ac("SPEC-100126-5445/AC-6")
async def test_rewording_keeps_applicability_and_evidence_union() -> None:
    """Dedup replaces the text; the contexts and evidence underneath union."""
    store = InMemoryLearningStore()
    first = Learning(
        trigger_keys=["deploy"],
        learning="snapshot first",
        run_id="run-1",
        works_when=["cold starts"],
        avoid_in=["migrations"],
        evidence_run_ids=["run-0"],
        confidence=0.6,
    )
    await store.store(first)
    reworded = Learning(
        trigger_keys=["deploy"],
        learning="snapshot before deploy (reworded)",
        run_id="run-2",
        works_when=["prod deploys"],
        evidence_run_ids=["run-0"],
        confidence=0.8,
    )
    await store.store(reworded)

    assert first.learning == "snapshot before deploy (reworded)"
    # The producer moved with the text (#709), and the outgoing producer
    # survives as evidence: provenance is not lost to the reword.
    assert first.run_id == "run-2"
    assert set(first.evidence_run_ids) == {"run-0", "run-1"}
    assert first.works_when == ["cold starts", "prod deploys"]
    assert first.avoid_in == ["migrations"]
    assert first.confidence == 0.8


@pytest.mark.ac("SPEC-100126-5445/AC-6")
async def test_merge_applicability_keeps_strongest_confidence() -> None:
    existing = Learning(confidence=0.4, works_when=["a"])
    incoming = Learning(confidence=0.9, works_when=["a", "b"])
    merge_applicability(existing, incoming)
    assert existing.confidence == 0.9
    assert existing.works_when == ["a", "b"]

    weakened = Learning(confidence=0.1)
    merge_applicability(existing, weakened)
    assert existing.confidence == 0.9


@pytest.mark.ac("SPEC-100126-5445/AC-6")
async def test_merge_applicability_keeps_measured_over_reported_prior() -> None:
    """A mostly-failing row must not be lifted by an unvalidated 0.9 prior."""
    existing = Learning(run_id="r1", confidence=0.2, success_after_use=1, failure_after_use=4)
    incoming = Learning(run_id="r2", epistemic_type=EpistemicType.REPORTED, confidence=0.9)
    merge_applicability(existing, incoming)
    assert existing.confidence == pytest.approx(0.2)
    assert existing.evidence_run_ids == ["r2"]  # still answerable to r2

    # and the row still cannot drift from its counters
    merge_applicability(existing, Learning(confidence=1.0))
    assert existing.confidence == pytest.approx(0.2)


@pytest.mark.ac("SPEC-100126-5445/AC-2")
async def test_epistemic_type_breaks_keyword_ties_in_retrieval() -> None:
    """Equal keyword hits: the tested claim outranks the counterfactual one."""
    store = InMemoryLearningStore()
    tested = Learning(
        trigger_keys=["deploy"],
        learning="tested path",
        epistemic_type=EpistemicType.TESTED,
        status="active",
    )
    counterfactual = Learning(
        trigger_keys=["deploy"],
        learning="would-have-worked path",
        epistemic_type=EpistemicType.COUNTERFACTUAL,
        status="active",
    )
    # Different tools so dedup keeps both rows.
    tested.tool_name = "a"
    counterfactual.tool_name = "b"
    await store.store(counterfactual)  # inserted first on purpose
    await store.store(tested)

    results = await store.find_relevant("deploy")
    assert [lr.learning for lr in results] == ["tested path", "would-have-worked path"]


@pytest.mark.ac("SPEC-100126-5445/AC-2")
async def test_epistemic_bonus_never_overrides_relevance() -> None:
    """A one-hit match beats a max-bonus zero-hit miss: bonuses stay < 1.0."""
    store = InMemoryLearningStore()
    relevant = Learning(trigger_keys=["deploy"], learning="relevant", tool_name="a")
    exotic = Learning(
        trigger_keys=["other"],
        learning="epistemically blessed",
        epistemic_type=EpistemicType.TESTED,
        tool_name="b",
    )
    await store.store(relevant)
    await store.store(exotic)
    results = await store.find_relevant("deploy")
    assert [lr.learning for lr in results] == ["relevant"]


class TestCoinSwarmWisdomImport:
    @pytest.mark.ac("SPEC-100126-5445/AC-1")
    def test_wisdom_maps_excels_and_avoid(self) -> None:
        learning = learning_from_wisdom(
            {
                "id": "17",
                "lesson": "Prefer limit orders during low-liquidity windows",
                "excels_in": ["low-liquidity windows", "high-volatility pairs"],
                "avoid_in": ["illiquid pairs"],
                "confidence": 0.93,
            },
            org_id="org-1",
        )
        assert learning.category == "wisdom"
        assert learning.learning == "Prefer limit orders during low-liquidity windows"
        assert learning.works_when == ["low-liquidity windows", "high-volatility pairs"]
        assert learning.avoid_in == ["illiquid pairs"]
        assert learning.confidence == pytest.approx(0.93)
        # The swarm asserts it; nothing here validated it.
        assert learning.epistemic_type == EpistemicType.REPORTED
        assert learning.source_query == "coinswarm:17"
        assert learning.org_id == "org-1"

    @pytest.mark.ac("SPEC-100126-5445/AC-1")
    def test_imported_wisdom_still_cannot_promote(self) -> None:
        """Confidence alone is not validation evidence — a Run/eval id is."""
        from maistro.memory.learnings.evidence import promotion_blockers

        learning = learning_from_wisdom({"lesson": "x", "confidence": 1.0})
        assert "no_source_run_or_evaluation_ids" in promotion_blockers(learning)

    @pytest.mark.ac("SPEC-100126-5445/AC-1")
    def test_confidence_clamped_and_junk_tolerated(self) -> None:
        learning = learning_from_wisdom(
            {"lesson": "x", "confidence": 5.0, "excels_in": "single string", "avoid_in": [1, "", 2]}
        )
        assert learning.confidence == 1.0
        assert learning.works_when == ["single string"]
        assert learning.avoid_in == ["1", "2"]

    @pytest.mark.ac("SPEC-100126-5445/AC-1")
    def test_empty_payload_yields_empty_learning(self) -> None:
        learning = learning_from_wisdom({})
        assert learning.learning == ""
        assert learning.confidence is None
        assert learning.epistemic_type == EpistemicType.REPORTED


class TestSqliteEpistemicRoundTrip:
    @pytest.fixture
    async def store(self) -> AsyncIterator[SqliteLearningStore]:
        conn = await aiosqlite.connect(":memory:")
        s = SqliteLearningStore(conn)
        await s.ensure_schema()
        yield s
        await conn.close()

    @pytest.mark.ac("SPEC-100126-5445/AC-2")
    async def test_epistemic_fields_survive_a_round_trip(self, store: SqliteLearningStore) -> None:
        await store.store(
            Learning(
                trigger_keys=["deploy"],
                learning="snapshot first",
                tool_name="bash",
                org_id="org-1",
                scope=MemoryScope.AGENT,
                epistemic_type=EpistemicType.TESTED,
                works_when=["cold starts", "prod deploys"],
                avoid_in=["migrations"],
                confidence=0.87,
                evidence_run_ids=["run-1", "run-2"],
                evaluation_ids=["eval-5"],
            )
        )
        (row,) = await store.list_all(org_id="org-1")
        assert row.epistemic_type == EpistemicType.TESTED
        assert row.works_when == ["cold starts", "prod deploys"]
        assert row.avoid_in == ["migrations"]
        assert row.confidence == pytest.approx(0.87)
        assert row.evidence_run_ids == ["run-1", "run-2"]
        assert row.evaluation_ids == ["eval-5"]

    @pytest.mark.ac("SPEC-100126-5445/AC-6")
    async def test_dedup_consolidates_evidence_in_sql(self, store: SqliteLearningStore) -> None:
        first = Learning(
            trigger_keys=["deploy"],
            learning="v1",
            tool_name="bash",
            org_id="org-1",
            works_when=["cold starts"],
            evidence_run_ids=["run-1"],
            confidence=0.5,
        )
        await store.store(first)
        reworded = Learning(
            trigger_keys=["deploy"],
            learning="v2 (reworded)",
            tool_name="bash",
            org_id="org-1",
            works_when=["prod deploys"],
            evidence_run_ids=["run-2"],
            run_id="run-2",
            confidence=0.9,
        )
        await store.store(reworded)

        (row,) = await store.list_all(org_id="org-1")
        # One surviving row. The SQL twins' dedup keeps the stored text and
        # bumps the hit counter (their documented contract); what it must do
        # either way is consolidate what the claim rests on.
        assert row.hit_count == 1
        assert set(row.works_when) == {"cold starts", "prod deploys"}
        assert set(row.evidence_run_ids) == {"run-1", "run-2"}
        assert row.confidence == pytest.approx(0.9)

    @pytest.mark.ac("SPEC-100126-5445/AC-6")
    async def test_dedup_keeps_the_ambient_run_as_evidence(
        self, store: SqliteLearningStore
    ) -> None:
        await store.store(
            Learning(
                trigger_keys=["deploy"],
                learning="v1",
                tool_name="bash",
                org_id="org-1",
                evidence_run_ids=["run-1"],
                confidence=0.5,
            )
        )
        # The rewording caller names no Run: the execution is ambient. The
        # merge must see the ids `store` resolved, not the blank learning
        # fields, or the deduplicated write loses the current execution.
        reworded = Learning(
            trigger_keys=["deploy"],
            learning="v2 (reworded)",
            tool_name="bash",
            org_id="org-1",
            confidence=0.9,
        )
        with bind_execution_context(run_id="run-ambient"):
            await store.store(reworded)

        (row,) = await store.list_all(org_id="org-1")
        assert set(row.evidence_run_ids) == {"run-1", "run-ambient"}
        # The surviving row keeps its original producer; the ambient Run is
        # evidence, not a re-attribution.
        assert row.run_id == ""

    @pytest.mark.ac("SPEC-100126-5445/AC-6")
    async def test_mark_outcome_measures_confidence_in_sql(
        self, store: SqliteLearningStore
    ) -> None:
        lid = await store.store(
            Learning(trigger_keys=["deploy"], learning="x", tool_name="bash", org_id="org-1")
        )
        (row,) = await store.list_all(org_id="org-1")
        assert row.confidence is None  # unmeasured before any outcome
        await store.mark_outcome([lid], success=False, org_id="org-1")
        await store.mark_outcome([lid], success=True, org_id="org-1")
        await store.mark_outcome([lid], success=True, org_id="org-1")
        (row,) = await store.list_all(org_id="org-1")
        assert row.confidence == pytest.approx(2 / 3)

    @pytest.mark.ac("SPEC-100126-5445/AC-6")
    async def test_legacy_file_upgrades_with_epistemic_columns(self) -> None:
        """A database written before M4-B3 gains the columns in place; legacy
        rows read back observed with no applicability and no measurement."""
        conn = await aiosqlite.connect(":memory:")
        store = SqliteLearningStore(conn)
        await conn.execute(
            "CREATE TABLE learnings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'general',"
            "trigger_keys TEXT NOT NULL DEFAULT '[]', learning TEXT NOT NULL DEFAULT '',"
            "tool_name TEXT NOT NULL DEFAULT '', source_query TEXT NOT NULL DEFAULT '',"
            "agent_id TEXT NOT NULL DEFAULT '', user_id TEXT,"
            "org_id TEXT NOT NULL DEFAULT '', team_id TEXT NOT NULL DEFAULT '',"
            "scope TEXT NOT NULL DEFAULT 'agent', hit_count INTEGER NOT NULL DEFAULT 0,"
            "status TEXT NOT NULL DEFAULT 'active', rca_category TEXT,"
            "rca_prevention TEXT NOT NULL DEFAULT '',"
            "success_after_use INTEGER NOT NULL DEFAULT 0,"
            "failure_after_use INTEGER NOT NULL DEFAULT 0)"
        )
        await conn.execute(
            "INSERT INTO learnings (learning, trigger_keys, tool_name, org_id) "
            "VALUES ('legacy', '[\"k\"]', 'bash', 'org-1')"
        )
        await conn.commit()

        await store.ensure_schema()
        (row,) = await store.list_all(org_id="org-1")
        assert row.epistemic_type == EpistemicType.OBSERVED
        assert row.works_when == []
        assert row.confidence is None
        await conn.close()
