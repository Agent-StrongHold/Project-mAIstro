"""Tests tied to SPEC.md §7 (Hypothesis-Tree Refinement) acceptance criteria
htr-1..7."""

from __future__ import annotations

import pytest

from maistro_rsi.htr import (
    HypothesisEvidence,
    HypothesisTree,
    NodeStatus,
)


def _evidence(*, tests_passed=True, won=0, battles=0, improved=False) -> HypothesisEvidence:
    return HypothesisEvidence(
        tests_passed=tests_passed,
        benchmarks_won=won,
        battles=battles,
        improved=improved,
    )


class TestEvidence:
    def test_rejects_impossible_tallies_and_computes_net_gain(self):
        """htr-1: impossible tallies raise; net_gain is +1/-1/0 for sweep/loss/split."""
        with pytest.raises(ValueError):
            HypothesisEvidence(tests_passed=True, benchmarks_won=3, battles=2, improved=True)
        with pytest.raises(ValueError):
            HypothesisEvidence(tests_passed=True, benchmarks_won=-1, battles=2, improved=False)
        with pytest.raises(ValueError):
            HypothesisEvidence(tests_passed=True, benchmarks_won=0, battles=-1, improved=False)

        assert _evidence(won=4, battles=4).net_gain == pytest.approx(1.0)
        assert _evidence(won=0, battles=4).net_gain == pytest.approx(-1.0)
        assert _evidence(won=2, battles=4).net_gain == pytest.approx(0.0)
        assert _evidence(won=0, battles=0).net_gain == 0.0


class TestNodeScore:
    def test_unscored_until_recorded_then_evidence_grounded(self):
        """htr-2: score is None pre-execution, 0.0 on failed tests, else net gain in [0,1]."""
        tree = HypothesisTree("root direction")
        root = tree.nodes[tree.root_id]
        assert root.score is None  # never a silent 0.0 for "unknown"

        # tests fail -> worthless regardless of a benchmark sweep
        a = tree.expand(root.id, "a")
        tree.record(a.id, _evidence(tests_passed=False, won=4, battles=4, improved=False))
        assert a.score == 0.0

        # clean sweep with tests passing -> 1.0
        b = tree.expand(root.id, "b")
        tree.record(b.id, _evidence(won=4, battles=4, improved=True))
        assert b.score == pytest.approx(1.0)

        # even split with tests passing -> 0.5
        c = tree.expand(root.id, "c")
        tree.record(c.id, _evidence(won=2, battles=4, improved=False))
        assert c.score == pytest.approx(0.5)


class TestExpand:
    def test_child_depth_parentage_and_guards(self):
        """htr-3: expand adds an OPEN child at depth+1, errors on unknown/abandoned parents."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        child = tree.expand(root.id, "try X")
        assert child.status is NodeStatus.OPEN
        assert child.depth == root.depth + 1
        assert child.id in root.children

        with pytest.raises(KeyError):
            tree.expand("does-not-exist", "y")

        # abandon the child, then refuse to grow it
        tree.record(child.id, _evidence(tests_passed=False, won=0, battles=2, improved=False))
        assert child.status is NodeStatus.ABANDONED
        with pytest.raises(ValueError):
            tree.expand(child.id, "z")


class TestRecord:
    def test_status_artifacts_and_auto_distill(self):
        """htr-4: record sets ABANDONED on no-progress, EXPLORED otherwise, stores artifacts, distills."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        # net gain <= 0 (even split) but tests pass -> still a dead end for the frontier
        flat = tree.expand(root.id, "flat change")
        tree.record(flat.id, _evidence(won=1, battles=2, improved=False))
        assert flat.status is NodeStatus.ABANDONED

        win = tree.expand(root.id, "real win")
        tree.record(
            win.id,
            _evidence(won=3, battles=4, improved=True),
            diff="diff-body",
            pr_url="http://pr/1",
            run_id="run123",
        )
        assert win.status is NodeStatus.EXPLORED
        assert win.artifacts == {"diff": "diff-body", "pr_url": "http://pr/1", "run_id": "run123"}
        assert win.insight is not None and "real win" in win.insight

    def test_explicit_insight_overrides_auto_distill(self):
        """htr-4: a supplied insight is kept verbatim instead of the distilled one."""
        tree = HypothesisTree("root")
        node = tree.expand(tree.root_id, "h")
        tree.record(node.id, _evidence(won=2, battles=2, improved=True), insight="custom lesson")
        assert node.insight == "custom lesson"


class TestBestNode:
    def test_returns_highest_score_with_deterministic_tiebreak(self):
        """htr-5: best_node is the top score, None until any run, shallower depth breaks ties."""
        tree = HypothesisTree("root")
        assert tree.best_node() is None

        root = tree.nodes[tree.root_id]
        shallow = tree.expand(root.id, "shallow")
        tree.record(shallow.id, _evidence(won=3, battles=4, improved=True))

        deep_parent = tree.expand(root.id, "deep parent")
        tree.record(deep_parent.id, _evidence(won=3, battles=4, improved=True))
        deep = tree.expand(deep_parent.id, "deep")
        tree.record(deep.id, _evidence(won=3, battles=4, improved=True))  # same score, deeper

        # all three share the same score; the shallowest (depth 1, earliest) wins
        assert tree.best_node().id == shallow.id

        # a strictly better node takes over
        winner = tree.expand(root.id, "winner")
        tree.record(winner.id, _evidence(won=4, battles=4, improved=True))
        assert tree.best_node().id == winner.id


class TestFrontier:
    def test_pending_prefers_stronger_parent_seeds_are_explored_only(self):
        """htr-6: pending is OPEN-only ordered by parent score; expandable_seeds is EXPLORED-only."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        strong = tree.expand(root.id, "strong parent")
        tree.record(strong.id, _evidence(won=4, battles=4, improved=True))  # score 1.0
        weak = tree.expand(root.id, "weak parent")
        tree.record(weak.id, _evidence(won=3, battles=4, improved=True))  # score 0.875

        child_of_strong = tree.expand(strong.id, "from strong")
        child_of_weak = tree.expand(weak.id, "from weak")

        pending_ids = [n.id for n in tree.pending()]
        # both OPEN children present; the one off the higher-scoring parent first
        assert pending_ids[0] == child_of_strong.id
        assert child_of_weak.id in pending_ids
        # explored/abandoned nodes are not pending
        assert strong.id not in pending_ids

        seed_ids = {n.id for n in tree.expandable_seeds()}
        assert seed_ids == {strong.id, weak.id}  # EXPLORED only, root (OPEN) excluded

    def test_pending_excludes_descendants_of_abandoned_ancestors(self):
        """htr-6: pending excludes OPEN children of abandoned parents — pruned branches do not re-grow."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        # Create a branch, queue a child while parent is OPEN, then abandon the parent
        dead_branch = tree.expand(root.id, "dead branch")
        orphan = tree.expand(dead_branch.id, "orphan")  # queue child before abandoning parent
        tree.record(dead_branch.id, _evidence(tests_passed=False, won=0, battles=2, improved=False))

        # Create a good branch with a queued child
        good_branch = tree.expand(root.id, "good branch")
        tree.record(good_branch.id, _evidence(won=3, battles=4, improved=True))
        child_of_good = tree.expand(good_branch.id, "child of good")

        pending_ids = [n.id for n in tree.pending()]
        # only the child of the good branch should be pending
        assert child_of_good.id in pending_ids
        # the orphan (child of abandoned parent) must not be queued
        assert orphan.id not in pending_ids

    def test_select_seed_raises_when_root_abandoned_and_no_seeds(self):
        """htr-6: select_seed raises ValueError if root is abandoned and no explored branches exist."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        # Abandon the root on first attempt, leaving no EXPLORED branches
        tree.record(root.id, _evidence(tests_passed=False, won=0, battles=2, improved=False))

        # Now select_seed should raise because root is abandoned and nothing is explored
        with pytest.raises(ValueError, match="root is abandoned and no explored branches exist"):
            tree.select_seed()


class TestDistilledInsights:
    def test_lineage_insights_oldest_first_deduped(self):
        """htr-7: distilled_insights walks root->node lineage, oldest first, de-duplicated."""
        tree = HypothesisTree("root")
        root = tree.nodes[tree.root_id]

        a = tree.expand(root.id, "a")
        tree.record(a.id, _evidence(won=3, battles=4, improved=True), insight="lesson-A")
        b = tree.expand(a.id, "b")
        tree.record(b.id, _evidence(won=4, battles=4, improved=True), insight="lesson-B")
        # a sibling lesson that must NOT leak into b's lineage
        other = tree.expand(root.id, "other")
        tree.record(other.id, _evidence(won=4, battles=4, improved=True), insight="lesson-OTHER")

        assert tree.distilled_insights(b.id) == ["lesson-A", "lesson-B"]

        # no-arg follows the best node's lineage (best == a full sweep at depth 1, 'other')
        assert tree.distilled_insights() == ["lesson-OTHER"]

    def test_duplicate_insights_collapse(self):
        """htr-7: a repeated insight along a lineage appears once."""
        tree = HypothesisTree("root")
        a = tree.expand(tree.root_id, "a")
        tree.record(a.id, _evidence(won=3, battles=4, improved=True), insight="same")
        b = tree.expand(a.id, "b")
        tree.record(b.id, _evidence(won=3, battles=4, improved=True), insight="same")
        assert tree.distilled_insights(b.id) == ["same"]


class TestTreePersistence:
    """Tests tied to SPEC.md §7 acceptance criteria htr-8..9."""

    def _grown_tree(self) -> HypothesisTree:
        tree = HypothesisTree("root direction")
        child = tree.expand(tree.root_id, "child idea")
        tree.expand(tree.root_id, "second idea")
        tree.record(
            tree.root_id,
            HypothesisEvidence(tests_passed=True, benchmarks_won=2, battles=2, improved=True),
            diff="the-diff",
            pr_url="http://pr/1",
            run_id="r1",
        )
        tree.record(
            child.id,
            HypothesisEvidence(tests_passed=False, benchmarks_won=0, battles=2, improved=False),
            insight="child broke the build",
        )
        return tree

    def test_round_trip_is_lossless(self):
        """htr-8: to_dict/from_dict preserves statuses, scores, evidence,
        insights, artifacts, children, and priority order — pending(),
        best_node(), distilled_insights(), summary() identical after reload."""
        tree = self._grown_tree()
        restored = HypothesisTree.from_dict(tree.to_dict())

        assert restored.to_dict() == tree.to_dict()
        assert [n.id for n in restored.pending()] == [n.id for n in tree.pending()]
        assert restored.best_node().id == tree.best_node().id
        assert restored.distilled_insights() == tree.distilled_insights()
        assert restored.summary() == tree.summary()
        for node_id, node in tree.nodes.items():
            twin = restored.nodes[node_id]
            assert twin.status is node.status
            assert twin.score == node.score
            assert twin.insight == node.insight
            assert twin.artifacts == node.artifacts
            assert twin.children == node.children

    def test_order_counter_restored_for_post_resume_expansion(self):
        """htr-9: expand() after from_dict produces globally unique,
        correctly prioritized orderings — as if the process never restarted."""
        tree = self._grown_tree()
        max_order = max(n.order for n in tree.nodes.values())

        restored = HypothesisTree.from_dict(tree.to_dict())
        fresh = restored.expand(restored.root_id, "post-resume idea")

        assert fresh.order == max_order + 1
        orders = [n.order for n in restored.nodes.values()]
        assert len(orders) == len(set(orders))  # no collisions
        # recency tie-break: the just-added node outranks the older pending one
        assert restored.pending()[0].id == fresh.id

    def test_from_dict_rejects_empty_and_dangling_root(self):
        """htr-9: restoring an empty tree or a root_id not among the nodes
        raises ValueError instead of building a corrupt tree."""
        with pytest.raises(ValueError, match="empty"):
            HypothesisTree.from_dict({"root_id": "x", "nodes": []})

        tree = HypothesisTree("root")
        data = tree.to_dict()
        data["root_id"] = "not-a-node"
        with pytest.raises(ValueError, match="root_id"):
            HypothesisTree.from_dict(data)
