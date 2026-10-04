"""M5-B stall detection, lineage review, and reseeding (SPEC.md §11, §8, §10).

Acceptance criteria verified here: intervention-1..7 (the policy itself),
coordinator-6 (the coordinator folds cycle outcomes into the policy, logs the
stall with its configured threshold, and appends the intervention), and
autorun-13..15 (config wiring, the objective.parked backlog hand-off, and the
LLM lineage reviewer's boundary + fallback behavior).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from maistro_rsi.autorun import (
    AuditLog,
    AutorunConfig,
    ExecutionReport,
    HtrContext,
    HtrCoordinator,
    make_llm_lineage_reviewer,
    run_autonomous,
)
from maistro_rsi.htr import HypothesisEvidence, HypothesisTree, NodeStatus
from maistro_rsi.intervention import (
    InterventionConfig,
    InterventionPolicy,
    LineageReviewContext,
    LineageStep,
    ObjectiveParked,
    ReseedDirection,
    StallTracker,
    materially_distinct,
    template_lineage_reviewer,
)


def _report(*, improved: bool, won: int = 2, battles: int = 3) -> ExecutionReport:
    """A non-improving-but-EXPLORED default: tests pass and net gain stays
    positive (2/3) so the branch survives as archived-promising, while the
    strict-majority rule keeps ``improved`` False."""
    return ExecutionReport(
        evidence=HypothesisEvidence(
            tests_passed=True, benchmarks_won=won, battles=battles, improved=improved
        )
    )


async def _reviewer(
    directions: list[ReseedDirection], seen: list[LineageReviewContext] | None = None
):
    async def _review(context: LineageReviewContext):
        if seen is not None:
            seen.append(context)
        return directions

    return _review


async def _null_reviewer(context: LineageReviewContext) -> list[ReseedDirection]:
    """An async reviewer that returns nothing — the LineageReviewer shape."""
    return []


def _stalled_tree() -> tuple[HypothesisTree, str]:
    """A tree with an explored root, an abandoned dead end, and an older
    promising branch that is *not* the champion — the archive shape a stall
    intervention must be able to see."""
    tree = HypothesisTree("improve the loop")
    champion = tree.expand(tree.root_id, "champion direction")
    tree.record(
        champion.id,
        # 2/3 wins: EXPLORED and the best branch, but not a perfect 1.0 score,
        # so a later 3/3 branch can measure a positive subsequent gain.
        HypothesisEvidence(tests_passed=True, benchmarks_won=2, battles=3, improved=True),
        insight="champion lesson",
    )
    older = tree.expand(tree.root_id, "older promising direction")
    tree.record(
        older.id,
        HypothesisEvidence(tests_passed=True, benchmarks_won=2, battles=3, improved=True),
        insight="older lesson",
    )
    dead_end = tree.expand(champion.id, "broke the suite")
    tree.record(
        dead_end.id,
        HypothesisEvidence(tests_passed=False, benchmarks_won=0, battles=3, improved=False),
        insight="avoid breaking the suite",
    )
    return tree, dead_end.id


class TestStallTracker:
    def test_rejects_non_positive_threshold(self):
        """intervention-1: a non-positive stall threshold is a configuration
        error rejected at construction, not a runtime surprise."""
        with pytest.raises(ValueError):
            StallTracker(0)
        with pytest.raises(ValueError):
            StallTracker(-1)

    def test_fires_exactly_once_at_threshold_and_resets(self):
        """intervention-1: consecutive non-improving cycles fire exactly once
        when the threshold is reached; an improving cycle (or reset()) zeroes
        the count."""
        tracker = StallTracker(3)
        assert tracker.record(improved=False) is False
        assert tracker.record(improved=False) is False
        assert tracker.record(improved=False) is True  # threshold reached
        assert tracker.record(improved=False) is False  # already fired
        assert tracker.consecutive_non_improving == 4
        tracker.record(improved=True)
        assert tracker.consecutive_non_improving == 0
        tracker.record(improved=False)
        tracker.record(improved=False)
        tracker.reset()
        assert tracker.consecutive_non_improving == 0


class TestReviewContext:
    async def test_reviewer_sees_full_lineage_with_evidence_and_archive(self):
        """intervention-2: the review context presents the full root-to-failure
        lineage with every ancestor's evidence and insight — never only the
        latest failed candidate — plus archived promising candidates including
        an older branch that is not the champion."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(
            config=InterventionConfig(stall_threshold=2), reviewer=_null_reviewer
        )
        context = policy.review_context(tree, failed_id)

        hypotheses = [step.hypothesis for step in context.lineage]
        assert hypotheses == [
            "improve the loop",
            "champion direction",
            "broke the suite",
        ]
        failed_step = context.lineage[-1]
        assert failed_step.tests_passed is False
        assert failed_step.status == NodeStatus.ABANDONED.value
        champion_step = context.lineage[1]
        assert champion_step.tests_passed is True
        assert champion_step.insight == "champion lesson"
        # archive: only EXPLORED nodes, champion first, older branch present
        archive_ids = [c.node_id for c in context.archive]
        assert tree.nodes[failed_id].id not in archive_ids  # abandoned excluded
        assert len(archive_ids) == 2
        assert context.archive[0].node_id == champion_step.node_id
        older = [c for c in context.archive if c.hypothesis == "older promising direction"]
        assert older and older[0].score == pytest.approx((1 / 3 + 1) / 2)

    async def test_archive_limit_bounds_presented_candidates(self):
        """intervention-2: archive_limit bounds how many archived candidates the
        reviewer may see."""
        tree = HypothesisTree("root")
        for i in range(5):
            node = tree.expand(tree.root_id, f"branch {i}")
            tree.record(
                node.id,
                HypothesisEvidence(tests_passed=True, benchmarks_won=3, battles=3, improved=True),
            )
        policy = InterventionPolicy(
            config=InterventionConfig(archive_limit=2), reviewer=_null_reviewer
        )
        context = policy.review_context(tree, tree.root_id)
        assert len(context.archive) == 2


class TestMateriallyDistinct:
    def _context(self, *hypotheses: str) -> LineageReviewContext:
        steps = tuple(
            LineageStep(node_id=f"n{i}", hypothesis=h, depth=i, status=NodeStatus.ABANDONED.value)
            for i, h in enumerate(hypotheses)
        )
        return LineageReviewContext(
            failed_node_id="n0", stalled_cycles=3, lineage=steps, archive=()
        )

    def test_drops_duplicates_rewords_and_blanks(self):
        """intervention-3: directions duplicating each other, rewording an
        already-tried hypothesis (case/punctuation/whitespace-insensitive), or
        blank are dropped; survivors keep their seed binding."""
        context = self._context("cache the scout results", "tighten the mutation gate")
        directions = [
            ReseedDirection(text="Cache the scout results!"),  # reword of tried #1
            ReseedDirection(text="  tighten   the MUTATION gate. "),  # reword of tried #2
            ReseedDirection(text=""),  # blank
            ReseedDirection(text="batch the benchmark runner"),  # distinct
            ReseedDirection(text="Batch the benchmark runner"),  # duplicate of survivor
            ReseedDirection(text="profile the harness loop", seed_node_id="abc"),  # distinct
        ]
        distinct = materially_distinct(directions, context)
        assert [d.text for d in distinct] == [
            "batch the benchmark runner",
            "profile the harness loop",
        ]
        assert distinct[1].seed_node_id == "abc"


class TestIntervene:
    async def test_reseeds_from_named_archived_nodes_with_provenance(self):
        """intervention-4: each surviving direction becomes an OPEN child of the
        archived candidate it names — an older promising node, not only the
        champion/latest — reseeded nodes carry their intervention_id artifact,
        and the record preserves directions verbatim, seed ids, lineage,
        archive, and cost."""
        tree, failed_id = _stalled_tree()
        older = next(n for n in tree.nodes.values() if n.hypothesis == "older promising direction")
        seen: list[LineageReviewContext] = []
        policy = InterventionPolicy(
            config=InterventionConfig(stall_threshold=3, direction_count=3),
            reviewer=await _reviewer(
                [
                    ReseedDirection(
                        text="exploit the older branch differently", seed_node_id=older.id
                    ),
                    ReseedDirection(text="batch the benchmark runner"),
                ],
                seen,
            ),
        )
        for _ in range(3):
            policy.observe(improved=False)

        intervention = await policy.intervene(tree, failed_id)

        # The direction with no seed falls back to the tree's most promising
        # seed (the champion); the named older branch is used verbatim.
        assert len(intervention.seed_node_ids) == 2
        named = tree.nodes[intervention.seed_node_ids[0]]
        assert named.parent_id == older.id
        assert named.status is NodeStatus.OPEN
        assert named.artifacts["intervention_id"] == "0"
        fallback = tree.nodes[intervention.seed_node_ids[1]]
        assert fallback.parent_id == tree.expandable_seeds()[0].id
        assert fallback.artifacts["intervention_id"] == "0"
        # provenance: directions verbatim, snapshot, cost, gain-not-yet
        assert [d.text for d in intervention.directions] == [
            "exploit the older branch differently",
            "batch the benchmark runner",
        ]
        assert intervention.trigger_node_id == failed_id
        assert intervention.stalled_cycles == 3
        assert intervention.stall_threshold == 3
        assert [s.hypothesis for s in intervention.lineage] == [
            "improve the loop",
            "champion direction",
            "broke the suite",
        ]
        assert intervention.cost["stalled_cycles"] == 3
        assert intervention.reviewer_seconds >= 0.0
        assert intervention.subsequent_gain is None
        assert intervention.to_dict()["directions"][0]["text"].startswith("exploit")
        # the reviewer saw the failed node and the stalled count
        assert seen[0].failed_node_id == failed_id
        assert seen[0].stalled_cycles == 3
        # tracker reset so the next stall needs a fresh N consecutive misses
        assert policy.tracker.consecutive_non_improving == 0

    async def test_unknown_or_abandoned_seed_falls_back(self):
        """intervention-4: a direction naming an unknown or ABANDONED node falls
        back to the tree's own most promising seed instead of raising."""
        tree, failed_id = _stalled_tree()
        dead_end_id = failed_id
        policy = InterventionPolicy(
            config=InterventionConfig(direction_count=2),
            reviewer=await _reviewer(
                [
                    ReseedDirection(text="ghost seed", seed_node_id="does-not-exist"),
                    ReseedDirection(text="abandoned seed", seed_node_id=dead_end_id),
                ]
            ),
        )
        policy.observe(improved=False)
        intervention = await policy.intervene(tree, failed_id)
        assert all(
            tree.nodes[sid].parent_id != "does-not-exist" for sid in intervention.seed_node_ids
        )
        assert all(tree.nodes[sid].status is NodeStatus.OPEN for sid in intervention.seed_node_ids)
        # neither direction re-grew the abandoned dead end
        assert all(tree.nodes[sid].parent_id != dead_end_id for sid in intervention.seed_node_ids)

    async def test_distinctness_filter_drops_tried_rewords(self):
        """intervention-4: a reviewer returning only reworded tried hypotheses
        reseeds nothing — the loop is never re-fed its own dead ends."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(
            config=InterventionConfig(direction_count=2),
            reviewer=await _reviewer(
                [ReseedDirection(text="CHAMPION direction!"), ReseedDirection(text="  ")]
            ),
        )
        policy.observe(improved=False)
        intervention = await policy.intervene(tree, failed_id)
        assert intervention.directions == ()
        assert intervention.seed_node_ids == ()

    async def test_gain_measured_after_subsequent_cycles(self):
        """intervention-5: every post-intervention cycle re-measures the
        intervention's subsequent_gain as the best-score delta; a real gain is
        positive, a flat follow-up is zero."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(
            config=InterventionConfig(stall_threshold=1, direction_count=1),
            reviewer=await _reviewer([ReseedDirection(text="fresh direction")]),
        )
        policy.observe(improved=False)
        intervention = await policy.intervene(tree, failed_id)
        trigger_best = intervention.best_score_at_trigger

        policy.observe_post_intervention_cycle(tree, improved=False)
        assert intervention.subsequent_gain == 0.0

        winner = tree.nodes[intervention.seed_node_ids[0]]
        tree.record(
            winner.id,
            HypothesisEvidence(tests_passed=True, benchmarks_won=3, battles=3, improved=True),
        )
        policy.observe_post_intervention_cycle(tree, improved=True)
        assert intervention.subsequent_gain == pytest.approx(1.0 - trigger_best)
        assert intervention.subsequent_gain > 0

    async def test_parks_after_configured_gainless_interventions(self):
        """intervention-6: after park_after interventions with no gain the next
        stall raises ObjectiveParked carrying the objective and every
        intervention record, instead of intervening again."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(
            config=InterventionConfig(stall_threshold=1, direction_count=1, park_after=2),
            reviewer=await _reviewer([ReseedDirection(text="same-ish direction")]),
        )

        # Intervention 1: first stall.
        policy.observe(improved=False)
        first = await policy.intervene(tree, failed_id)
        # A non-improving post-intervention cycle records a zero gain...
        policy.observe_post_intervention_cycle(tree, improved=False)
        # ...and the next stall is still under park_after -> intervene again.
        policy.observe(improved=False)
        second = await policy.intervene(tree, failed_id)
        assert first.index == 0 and second.index == 1

        # Second gainless cycle: now both interventions are gainless, so the
        # next stall parks the objective instead of intervening a third time.
        policy.observe_post_intervention_cycle(tree, improved=False)
        policy.observe(improved=False)
        with pytest.raises(ObjectiveParked) as excinfo:
            await policy.intervene(tree, failed_id)
        assert excinfo.value.objective == "improve the loop"
        assert excinfo.value.interventions == (first, second)


class TestTemplateReviewerAndConfig:
    def test_template_reviewer_binds_one_direction_per_archive_candidate(self):
        """intervention-7: the deterministic reviewer returns one
        archive-grounded, seed-bound direction per archived candidate, and
        degrades to the failed node when the archive is empty."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(config=InterventionConfig(), reviewer=_null_reviewer)
        context = policy.review_context(tree, failed_id)
        directions = template_lineage_reviewer(context)
        assert len(directions) == len(context.archive)
        assert [d.seed_node_id for d in directions] == [c.node_id for c in context.archive]
        assert all("avoiding the recorded lesson" in d.text for d in directions)

        empty = LineageReviewContext(
            failed_node_id=failed_id,
            stalled_cycles=3,
            lineage=(LineageStep(node_id="x", hypothesis="h", depth=1, status="abandoned"),),
            archive=(),
        )
        fallback = template_lineage_reviewer(empty)
        assert len(fallback) == 1 and fallback[0].seed_node_id == failed_id

    def test_config_validates_every_knob(self):
        """intervention-7: every policy knob must be positive at construction."""
        with pytest.raises(ValueError):
            InterventionConfig(stall_threshold=0)
        with pytest.raises(ValueError):
            InterventionConfig(direction_count=0)
        with pytest.raises(ValueError):
            InterventionConfig(park_after=0)
        with pytest.raises(ValueError):
            InterventionConfig(archive_limit=0)
        assert InterventionConfig().stall_threshold == 3


class TestCoordinatorIntervention:
    @pytest.mark.asyncio
    async def test_stall_is_logged_with_threshold_and_intervention_appended(self):
        """coordinator-6: the coordinator folds each cycle's outcome into the
        policy; at the configured threshold it logs htr_stall_detected carrying
        the configured stall_threshold, performs exactly one intervention per
        stall, and appends it to CoordinatorResult.interventions."""
        tree = HypothesisTree("root idea")
        directions = [ReseedDirection(text="a genuinely new direction")]
        policy = InterventionPolicy(
            config=InterventionConfig(stall_threshold=2, direction_count=1),
            reviewer=await _reviewer(directions),
        )

        async def executor(context: HtrContext) -> ExecutionReport:
            return _report(improved=False)

        with capture_logs() as logs:
            result = await HtrCoordinator(tree, executor, policy=policy).run(3, lambda ctx: "next")

        stall_events = [e for e in logs if e.get("event") == "htr_stall_detected"]
        assert len(stall_events) == 1
        assert stall_events[0]["stall_threshold"] == 2
        assert stall_events[0]["consecutive_non_improving"] == 2
        assert len(result.interventions) == 1
        assert result.interventions[0].directions[0].text == "a genuinely new direction"
        # the reseeded direction is acted on before any new proposal
        assert tree.nodes[result.steps[-1]].hypothesis == "a genuinely new direction"
        reseed_events = [e for e in logs if e.get("event") == "htr_intervention_reseeded"]
        assert len(reseed_events) == 1
        assert reseed_events[0]["stall_threshold"] == 2

    @pytest.mark.asyncio
    async def test_no_policy_keeps_original_behavior(self):
        """coordinator-6: without a policy the coordinator behaves exactly as
        before — no stall logging, no interventions."""
        tree = HypothesisTree("root idea")

        async def executor(context: HtrContext) -> ExecutionReport:
            return _report(improved=False)

        with capture_logs() as logs:
            result = await HtrCoordinator(tree, executor).run(2, lambda ctx: "next")
        assert result.interventions == []
        assert not [e for e in logs if e.get("event") == "htr_stall_detected"]


def _autorun_config(tmp_path: Path, **overrides) -> AutorunConfig:
    base = {
        "repo_url": "https://github.com/org/repo.git",
        "test_command": "pytest -q",
        "num_cycles": 6,
        "workspace_root": str(tmp_path),
    }
    base.update(overrides)
    return AutorunConfig(**base)


class TestAutorunStallWiring:
    @pytest.mark.asyncio
    async def test_config_wired_and_interventions_accumulated(self, monkeypatch, tmp_path):
        """autorun-13: run_autonomous wires the configured policy (stall
        threshold / direction count / park_after) into its coordinator and the
        returned result accumulates every intervention; reseeded directions run
        as cycles of their own."""
        monkeypatch.setattr(
            "maistro_rsi.autorun._post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError())
        )  # reviewer degrades to the deterministic template reviewer

        async def executor(context: HtrContext) -> ExecutionReport:
            # EXPLORED (net gain 1/3) but never a strict-majority improvement:
            # every cycle is non-improving, so the loop stalls immediately.
            return _report(improved=False)

        config = _autorun_config(
            tmp_path, stall_threshold=2, direction_count=2, park_after=5, num_cycles=3
        )
        result = await run_autonomous(config, executor=executor, proposer=lambda ctx: "next")

        assert len(result.interventions) == 1  # one stall -> one intervention
        intervention = result.interventions[0]
        assert intervention.stalled_cycles == 2
        assert intervention.stall_threshold == 2
        assert len(intervention.directions) == 2  # direction_count honored
        assert all(d.seed_node_id for d in intervention.directions)
        # the reseeded directions were executed as cycles
        reseeded = [result.tree.nodes[nid].hypothesis for nid in result.steps]
        assert any("Alternative direction" in h for h in reseeded)
        # the reseeded nodes carry their intervention provenance in the tree
        assert any(
            node.artifacts.get("intervention_id") == "0" for node in result.tree.nodes.values()
        )
        # the intervention's cost is measurable, gain re-measured per cycle
        assert intervention.cost["stalled_cycles"] == 2
        assert intervention.subsequent_gain is not None

    @pytest.mark.asyncio
    async def test_parked_objective_recorded_to_backlog(self, monkeypatch, tmp_path):
        """autorun-14: repeated intervention without improvement parks the
        objective — the run stops cleanly, and an objective.parked record with
        the full intervention provenance lands in the append-only audit trail
        as the hand-off to the backlog policy."""
        monkeypatch.setattr(
            "maistro_rsi.autorun._post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError())
        )

        async def executor(context: HtrContext) -> ExecutionReport:
            return _report(improved=False)

        audit_path = tmp_path / "audit.jsonl"
        config = _autorun_config(
            tmp_path, stall_threshold=1, direction_count=1, park_after=1, num_cycles=10
        )
        result = await run_autonomous(
            config,
            executor=executor,
            proposer=lambda ctx: "next",
            audit=AuditLog(audit_path),
        )

        assert result.steps  # some cycles ran before the park
        assert len(result.interventions) == 1  # park_after=1: park on the 2nd stall
        parked_records = [
            json.loads(line)
            for line in audit_path.read_text().splitlines()
            if json.loads(line).get("event_type") == "objective.parked"
        ]
        assert len(parked_records) == 1
        record = parked_records[0]
        assert record["objective"] == config.root_hypothesis
        assert len(record["interventions"]) == 1
        assert record["interventions"][0]["stalled_cycles"] == 1
        assert record["interventions"][0]["subsequent_gain"] is not None
        assert record["interventions"][0]["directions"]
        # the trail stays parseable JSON lines end to end
        for line in audit_path.read_text().splitlines():
            json.loads(line)


class TestLlmLineageReviewer:
    def test_degrades_to_template_on_gateway_failure(self, monkeypatch):
        """autorun-15: an unreachable gateway degrades to the deterministic
        template reviewer — a stalled loop is never left with nothing to
        reseed from."""

        def boom(*args, **kwargs):
            raise ConnectionError("no gateway")

        monkeypatch.setattr("maistro_rsi.autorun._post", boom)
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(config=InterventionConfig(), reviewer=_null_reviewer)
        context = policy.review_context(tree, failed_id)
        reviewer = make_llm_lineage_reviewer()
        import asyncio

        directions = asyncio.run(reviewer(context))
        assert [d.seed_node_id for d in directions] == [
            d.seed_node_id for d in template_lineage_reviewer(context)
        ]

    def test_honors_seed_prefix_and_filters_unknown_seeds(self, monkeypatch):
        """autorun-15: SEED=<node_id> prefixes naming archived candidates are
        honored; directions naming unknown nodes lose the prefix but keep their
        text (the policy's own fallback decides the branch point)."""
        tree, failed_id = _stalled_tree()
        policy = InterventionPolicy(config=InterventionConfig(), reviewer=_null_reviewer)
        context = policy.review_context(tree, failed_id)
        archive_id = context.archive[0].node_id

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    f"SEED={archive_id} attack the older branch with caching\n"
                                    "SEED=zzz unknown seed falls back\n"
                                    "plain direction with no seed"
                                )
                            }
                        }
                    ]
                }

        monkeypatch.setattr("maistro_rsi.autorun._post", lambda *a, **k: _Resp())
        reviewer = make_llm_lineage_reviewer()
        import asyncio

        directions = asyncio.run(reviewer(context))
        assert directions[0].seed_node_id == archive_id
        assert directions[0].text == "attack the older branch with caching"
        assert directions[1].seed_node_id is None
        assert directions[1].text == "unknown seed falls back"
        assert directions[2].seed_node_id is None
        assert len(directions) == 3
