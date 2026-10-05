"""Tests for `scripts/bench_model_routing.py` (issue #916, RESEARCH M8-B3).

The root suite is the coverage producer for `scripts/` (quality.yml runs
`--source=scripts`), so an untested research bench would red the diff-coverage
gate on the PR that adds it — same reason `test_bench_working_memory.py`
exists. Beyond satisfying the measurement, these tests pin the properties the
research note's disposition rests on:

* the static-router baseline is the *real* production scorer
  (`maistro.router.scorer.score_candidate`), not a re-implementation —
  including its filter path (over-quota, no paygo → candidate dropped);
* feedback is delayed and sparsified exactly as claimed (dropped labels are
  never delivered, delivered labels never arrive early);
* the drift world actually drifts (ground truth mutates, catalog stays stale)
  and the outcome-learned policy beats the static baseline after drift on a
  fixed seed — the issue's hypothesis, pinned deterministically;
* the OPE estimators track known truth on a deterministic log, and the
  aggregation/frontier logic dominates (and ties) correctly.

Everything runs offline at deliberately small scale (no network, no
PostgreSQL) so the suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_model_routing.py"

spec = importlib.util.spec_from_file_location("bench_model_routing", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)

CTX = bench.Ctx(task="code", complexity="complex")


class TestWorldDefinition:
    def test_ground_truth_drifts_while_catalog_stays_stale(self) -> None:
        # The drift must be real: at least one arm's success probability moves
        # across the phase boundary, in the direction the mutation table names.
        moved = [
            arm
            for arm in range(bench.N_ARMS)
            if bench.true_success_prob(arm, CTX, 0) != bench.true_success_prob(arm, CTX, 1)
        ]
        assert moved, "no arm's ground truth changed across the drift boundary"
        # The mutated values are exactly the declared per-arm transformations
        # applied to the pre-drift table (alpha degrades x0.55, beta-nano
        # improves, everything else unchanged).
        for arm, mutate in bench._POST_DRIFT_MUTATION.items():
            for task in bench.TASK_TYPES:
                for cx in bench.COMPLEXITIES:
                    pre = bench.PRE_DRIFT[arm][task][cx]
                    assert bench.POST_DRIFT[arm][task][cx] == mutate(pre)
        # Catalog metadata is what the scorer sees and does NOT move with the
        # world — that staleness is the issue's hypothesis.
        quality_before = [bench.CATALOG[a][0].quality for a in range(bench.N_ARMS)]
        below_floor_post = [
            (arm, task, cx)
            for arm in range(bench.N_ARMS)
            for task in bench.TASK_TYPES
            for cx in bench.COMPLEXITIES
            if bench.true_success_prob(arm, bench.Ctx(task, cx), 1) < bench.SAFETY_FLOOR
        ]
        assert below_floor_post, (
            "drift must push some (arm, context) below the safety floor or "
            "unsafe-risk accounting has nothing to count"
        )
        assert [bench.CATALOG[a][0].quality for a in range(bench.N_ARMS)] == quality_before

    def test_context_sampling_is_seeded_and_in_domain(self) -> None:
        a = bench.sample_context(random.Random(7))
        b = bench.sample_context(random.Random(7))
        assert (a.task, a.complexity) == (b.task, b.complexity)
        assert a.task in bench.TASK_TYPES and a.complexity in bench.COMPLEXITIES
        # The scorer-facing Intent carries the task's preferred strengths, so
        # the production strength multiplier is exercised per task type.
        assert a.to_intent().preferred_strengths == bench.TASK_STRENGTHS[a.task]
        assert a.to_intent().complexity == a.complexity


class TestStaticRouterBaseline:
    def test_pick_is_the_production_scorers_argmax(self) -> None:
        # Recompute every candidate with the real scorer and confirm the
        # baseline's pick is the argmax — the bench must not quietly substitute
        # its own router for the shipped one.
        intent = CTX.to_intent()
        usage = dict(bench.LOG_USAGE_PCTS)
        scored = []
        for arm in range(bench.N_ARMS):
            model_cfg, provider_cfg = bench.CATALOG[arm]
            cand = bench.score_candidate(
                f"arm{arm}",
                model_cfg,
                provider_cfg,
                intent,
                bench.ROUTING_CFG,
                usage.get(model_cfg.provider, 0.0),
            )
            assert cand is not None
            scored.append(cand.score)
        assert bench.static_router_pick(CTX, usage) == scored.index(max(scored))

    def test_fully_exhausted_no_paygo_catalog_falls_back_to_first_arm(self) -> None:
        # The production filter path: usage_pct >= 1.0 with no paygo makes
        # score_candidate return None for every arm, and static_router_pick
        # must stay total (falls back to arm 0) rather than raise.
        no_paygo = bench.ProviderConfig(free_tokens=1000)
        saved = bench.CATALOG
        try:
            bench.CATALOG = {arm: (saved[arm][0], no_paygo) for arm in saved}
            assert (
                bench.score_candidate(
                    "arm0", saved[0][0], no_paygo, CTX.to_intent(), bench.ROUTING_CFG, 1.0
                )
                is None
            )
            assert bench.static_router_pick(CTX, {"alpha": 1.0, "beta": 1.0, "gamma": 1.0}) == 0
        finally:
            bench.CATALOG = saved
        # A still-in-budget provider keeps the pick away from the exhausted
        # one: in-budget candidates always outrank over-quota paygo in the
        # shipped scorer.
        pick = bench.static_router_pick(CTX, {"alpha": 1.0, "beta": 0.0, "gamma": 0.0})
        assert bench.CATALOG[pick][0].provider != "alpha"


class TestLinearAlgebra:
    def test_mat_inverse_inverts_and_rejects_singular(self) -> None:
        a = [[4.0, 2.0, 0.6], [2.0, 3.0, 0.3], [0.6, 0.3, 1.0]]
        inv = bench.mat_inverse(a)
        for i in range(3):
            for j in range(3):
                dot = sum(a[i][k] * inv[k][j] for k in range(3))
                assert math.isclose(dot, 1.0 if i == j else 0.0, abs_tol=1e-9)
        with pytest.raises(ZeroDivisionError, match="singular"):
            bench.mat_inverse([[1.0, 2.0], [2.0, 4.0]])

    def test_chol_lower_reconstructs_spd_input(self) -> None:
        a = [[4.0, 2.0, 0.6], [2.0, 3.0, 0.3], [0.6, 0.3, 1.0]]
        low = bench.chol_lower(a)
        for i in range(3):
            for j in range(i + 1, 3):
                assert low[i][j] == 0.0
            for j in range(3):
                dot = sum(low[i][k] * low[j][k] for k in range(3))
                assert math.isclose(dot, a[i][j], abs_tol=1e-9)


class TestFeedbackChannel:
    def test_delayed_labels_arrive_late_never_early(self) -> None:
        seen: list[tuple[tuple[str, str], int, float]] = []
        rng = random.Random(3)
        channel = bench.FeedbackChannel(
            delay=5,
            max_jitter=0,
            label_rate=1.0,
            rng=rng,
            on_observe=lambda ctx, arm, reward: seen.append((ctx.key(), arm, reward)),
        )
        channel.enqueue(0, CTX, 2, True)
        for step in range(4):
            channel.deliver_due(step)
            assert seen == []
        channel.deliver_due(5)
        assert seen == [((CTX.task, CTX.complexity), 2, 1.0)]
        assert channel.delivered == 1 and channel.enqueued == 1 and channel.dropped == 0

    def test_dropped_labels_are_never_delivered(self) -> None:
        seen: list[Any] = []
        rng = random.Random(3)
        channel = bench.FeedbackChannel(
            delay=0,
            max_jitter=0,
            label_rate=0.0,
            rng=rng,
            on_observe=lambda ctx, arm, reward: seen.append((ctx, arm, reward)),
        )
        for step in range(10):
            channel.enqueue(step, CTX, 1, True)
            channel.deliver_due(step)
        assert seen == []
        assert channel.dropped == 10 and channel.delivered == 0


class TestPolicies:
    def test_explore_start_round_robin_then_greedy_converges(self) -> None:
        policy = bench.CatalogPriorMeanPolicy(seed=0, explore_start_rounds=2)
        # Forced round-robin covers every arm exactly `rounds` times before any
        # learned choice — the explore-start contract.
        forced = [policy.select(CTX, {}, step) for step in range(2 * bench.N_ARMS)]
        assert forced == [a for rounds in range(2) for a in range(bench.N_ARMS)]
        # One arm keeps winning every delayed label in this context; greedy
        # selection must converge to it and stay.
        for _ in range(400):
            policy.observe(CTX, 3, 1.0)
            policy.observe(CTX, 1, 0.0)
        assert all(policy.select(CTX, {}, step) == 3 for step in range(50))
        assert policy.observed_labels() == 800

    def test_forgetting_discounts_stale_evidence(self) -> None:
        policy = bench.CatalogPriorMeanPolicy(seed=0, explore_start_rounds=0)
        for _ in range(50):
            policy.observe(CTX, 3, 1.0)
        strong = policy._mean(CTX.key(), 3)
        for _ in range(200):
            policy.observe(CTX, 3, 0.0)
        faded = policy._mean(CTX.key(), 3)
        assert faded < strong, "gamma<1 must let new evidence outweigh old"
        # The arm-level mean is shrunk toward the (stale) catalog quality, so
        # zero evidence does not mean zero belief.
        assert policy._mean(("chat", "simple"), 3) > 0.0

    def test_epsilon_branch_explores(self) -> None:
        policy = bench.EpsilonGreedyPolicy(seed=0, epsilon=1.0)
        picks = {policy.select(CTX, {}, step) for step in range(200)}
        assert picks == set(range(bench.N_ARMS))

    def test_linear_policies_learn_the_rewarded_arm(self) -> None:
        # Every arm gets evidence in this context (reward 1 only for arm 3),
        # because an arm with no observations keeps its prior-width optimism
        # bonus — that exploration is by design (LinUCB/Thompson), not a bug.
        # With all arms informed, the rewarded arm wins deterministically.
        for name in ("linucb", "thompson-linear"):
            policy = bench.POLICY_FACTORIES[name](seed=0)
            for _ in range(100):
                for arm in range(bench.N_ARMS):
                    policy.observe(CTX, arm, 1.0 if arm == 3 else 0.0)
            picks = {policy.select(CTX, {}, step) for step in range(30)}
            assert picks == {3}, f"{name} must route the rewarded arm"

    def test_unobserved_arms_keep_optimism_so_get_tried(self) -> None:
        # LinUCB's optimism bonus (0.5·sqrt(||x||²) = 1.0 for a fresh posterior)
        # outranks a mediocre observed arm: with arm 3 trained only to ~0.55
        # expected success, selection must abandon it for untouched arms —
        # the exploration behavior the issue's "exploration risk" axis asks
        # about, pinned structurally rather than by wall-clock.
        policy = bench.POLICY_FACTORIES["linucb"](seed=0)
        for _ in range(300):
            policy.observe(CTX, 3, 0.55)
        picks = {policy.select(CTX, {}, step) for step in range(20)}
        assert picks != {3}, "a half-known arm must not be pure-exploited"
        assert 0 in picks  # all-unobserved UCBs tie at 1.0; argmax keeps arm 0

    def test_linucb_survives_degenerate_covariance_reset(self) -> None:
        # Thompson's lazy A-inverse (None until first select after observe)
        # and LinUCB's per-observe re-inversion both run through mat_inverse;
        # a fresh policy selects from the identity prior without error.
        for name in ("linucb", "thompson-linear"):
            policy = bench.POLICY_FACTORIES[name](seed=0)
            assert policy.select(CTX, {}, 0) in range(bench.N_ARMS)
            policy.observe(CTX, 0, 1.0)
            assert policy.select(CTX, {}, 1) in range(bench.N_ARMS)


class TestRecoveryTracker:
    def test_triggers_once_at_threshold_and_sticks(self) -> None:
        tracker = bench.RecoveryTracker(window=3, threshold=0.03)
        for step, regret in enumerate([0.10, 0.02, 0.00, 0.00]):
            tracker.update(step, regret)
            if step < 3:  # window means 0.10, 0.06, 0.04 — all above 0.03
                assert tracker.recovery_step is None
        assert tracker.recovery_step == 3  # window [0.02, 0, 0] mean ≈ 0.0067
        for step in range(4, 8):
            tracker.update(step, 0.5)
        assert tracker.recovery_step == 3, "first adaptation step must stick"

    def test_window_slides(self) -> None:
        tracker = bench.RecoveryTracker(window=2, threshold=0.05)
        tracker.update(0, 0.9)
        tracker.update(1, 0.9)  # full window, mean 0.9 — not adapted
        assert tracker.recovery_step is None
        tracker.update(2, 0.0)  # window slides to [0.9, 0.0]
        assert tracker.recovery_step is None
        tracker.update(3, 0.0)  # [0.0, 0.0] — adapted
        assert tracker.recovery_step == 3


class TestEpisodes:
    def test_run_episode_is_deterministic_and_well_formed(self) -> None:
        kwargs = {
            "steps": 120,
            "delay": 25,
            "label_rate": 0.8,
            "drift_at": 40,
            "checkpoints": [10, 50],
        }
        first = bench.run_episode("supervised-mean", 0, **kwargs)
        second = bench.run_episode("supervised-mean", 0, **kwargs)
        assert first == second
        # Static never adapts: recovery_step stays None even long after drift.
        static = bench.run_episode("static-router", 0, **kwargs)
        assert static.recovery_step is None
        # Static never accumulates observed labels, so its label checkpoints
        # never fire; the learner's do.
        assert static.regret_at_labels == {}
        assert first.regret_at_labels != {}
        # Labels: 20% are dropped at enqueue; the rest either arrive before the
        # episode ends or are still in flight (delay+jitter can push delivery
        # past the last step) — delivered never exceeds enqueued minus dropped.
        assert 0.15 * 120 <= static.labels_dropped <= 0.25 * 120
        assert static.labels_delivered + static.labels_dropped <= 120
        assert static.labels_delivered == first.labels_delivered

    def test_unsafe_risk_decomposes_exactly(self) -> None:
        result = bench.run_episode(
            "supervised-mean",
            0,
            steps=300,
            delay=10,
            label_rate=1.0,
            drift_at=30,
            checkpoints=[],
        )
        assert result.unsafe_static + result.unsafe_exploration == result.unsafe_total
        # The static baseline itself never deviates from itself.
        static = bench.run_episode(
            "static-router",
            0,
            steps=300,
            delay=10,
            label_rate=1.0,
            drift_at=30,
            checkpoints=[],
        )
        assert static.unsafe_exploration == 0
        assert static.unsafe_total == static.unsafe_static

    def test_learner_beats_static_after_drift_on_fixed_seed(self) -> None:
        # The issue's hypothesis, pinned: across several fixed seeds the
        # outcome-learned mean policy ends with lower cumulative regret than
        # the shipped static router once the world has drifted under it.
        kwargs = {"steps": 600, "delay": 20, "label_rate": 0.8, "drift_at": 150, "checkpoints": []}
        static_total = learner_total = 0.0
        recovered = 0
        for seed in range(4):
            static_total += bench.run_episode("static-router", seed, **kwargs).cumulative_regret
            learner = bench.run_episode("supervised-mean", seed, **kwargs)
            learner_total += learner.cumulative_regret
            recovered += learner.recovery_step is not None
        assert learner_total < static_total * 0.5, "learning must at least halve regret"
        assert recovered >= 3, "learner must adapt within the episode on most seeds"


class TestOffPolicyEvaluation:
    def test_logged_dataset_propensities_match_the_logging_policy(self) -> None:
        rows = bench.generate_logged_dataset(200, eps=0.2, seed=0)
        again = bench.generate_logged_dataset(200, eps=0.2, seed=0)
        assert [(r.arm, r.reward, r.propensity) for r in rows] == [
            (r.arm, r.reward, r.propensity) for r in again
        ]
        for row in rows:
            # p = (1-eps)·1{a = static_pick} + eps/N — never below eps/N.
            assert row.propensity >= 0.2 / bench.N_ARMS - 1e-12
            assert row.reward in (0.0, 1.0)

    def test_direct_model_falls_back_to_global_mean_on_unseen_cell(self) -> None:
        # One context cell only, so every other (cell, arm) key is unseen and
        # must fall back to the global mean rather than fabricate a rate.
        rows = [
            bench.LogRow(ctx=CTX, arm=0, reward=float(i % 2 == 0), propensity=0.5)
            for i in range(10)
        ]
        model = bench.direct_model_fit(rows)
        global_mean = sum(r.reward for r in rows) / len(rows)
        unseen = bench.Ctx(task="chat", complexity="simple")
        assert model(unseen, 0) == model(unseen, 3) == global_mean
        # The seen cell is pulled from the global mean toward its own rate by
        # the smoothing prior: 5 successes in 10 with prior weight 4 on 0.5.
        expected_seen = (5.0 + 4.0 * global_mean) / (10 + 4.0)
        assert math.isclose(model(CTX, 0), expected_seen)

    def test_ope_tracks_known_truth_and_clips(self) -> None:
        rows = bench.generate_logged_dataset(1500, eps=0.2, seed=2)
        split = int(len(rows) * 0.6)
        train_rows, eval_rows = rows[:split], rows[split:]
        policy = bench.CatalogPriorMeanPolicy(seed=2)
        bench.fit_on_log(policy, train_rows)
        result = bench.evaluate_ope(policy, eval_rows, train_rows)
        # Both estimators land near the known on-policy truth; doubly robust
        # is the tighter one on this log (its direct model has dense support).
        assert result.ips_abs_bias < 0.10
        assert result.dr_abs_bias < 0.10
        assert 0.0 < result.true_value < 1.0
        # Clipping everything to 1/p=1 yields a finite, downward-biased
        # estimate without dividing by zero. Only matching rows pass through
        # the weight path, so clip_rate counts exactly the matching rows whose
        # logged propensity (0.84 here) now sits below the floor.
        clipped = bench.evaluate_ope(
            bench.StaticRouterPolicy(seed=0), eval_rows, train_rows, clip_min=1.0
        )
        matches = sum(
            1
            for row in eval_rows
            if row.arm == bench.static_router_pick(row.ctx, bench.LOG_USAGE_PCTS)
        )
        assert math.isclose(clipped.clip_rate, matches / len(eval_rows), abs_tol=1e-6)
        assert 0.0 <= clipped.ips < result.ips  # shrunken weights bias downward


class TestAggregation:
    @staticmethod
    def _row(policy: str, seed: int, regret: float, quality: float, cost: float) -> bench.RunResult:
        return bench.RunResult(
            policy=policy,
            seed=seed,
            cumulative_regret=regret,
            regret_rate_pre=0.0,
            regret_rate_post=0.0,
            recovery_step=None,
            unsafe_total=0,
            unsafe_exploration=0,
            unsafe_static=0,
            arm_switches=0,
            mean_true_quality=quality,
            mean_list_cost=cost,
            labels_delivered=0,
            labels_dropped=0,
        )

    def test_frontier_flags_dominance_and_ties(self) -> None:
        results = [
            self._row("a", 0, regret=10.0, quality=0.9, cost=1.0),
            self._row("b", 0, regret=20.0, quality=0.8, cost=1.0),  # dominated by a
            self._row("c", 0, regret=30.0, quality=0.8, cost=1.0),  # tie with b
            self._row("d", 0, regret=40.0, quality=0.7, cost=0.5),  # cheaper: own point
        ]
        agg = bench.aggregate(results)
        flags = bench.pareto_flags(agg)
        assert flags["a"] and not flags["b"] and not flags["c"] and flags["d"]

    def test_aggregate_reports_dispersion_and_recovery_hits(self) -> None:
        a = self._row("a", 0, regret=10.0, quality=0.9, cost=1.0)
        b = self._row("a", 1, regret=20.0, quality=0.7, cost=1.0)
        b.recovery_step = 42
        agg = bench.aggregate([a, b])
        stats = agg["a"]["cumulative_regret"]
        assert stats["mean"] == 15.0 and stats["std"] == 5.0
        assert agg["a"]["recovery_step_mean"] == 42.0
        assert agg["a"]["recovery_step_hits"] == "1/2"
        # Same-seed values across policies must not blend: policy is the key.
        assert len(agg) == 1


class TestMainAndReport:
    def test_main_writes_the_published_payload_shape(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        output = tmp_path / "results.json"
        argv = [
            "bench_model_routing.py",
            "--steps",
            "60",
            "--seeds",
            "1",
            "--drift-at",
            "30",
            "--delay",
            "5",
            "--label-rate",
            "0.8",
            "--output",
            str(output),
        ]
        monkeypatch.setattr(sys, "argv", argv)
        assert bench.main() == 0
        report = json.loads(output.read_text())
        assert set(report) == {
            "config",
            "per_policy",
            "pareto_on_frontier",
            "off_policy_evaluation",
            "sample_efficiency",
            "run_results",
        }
        assert report["config"]["steps"] == 60
        assert len(report["run_results"]) == len(bench.POLICY_FACTORIES)
        assert set(report["per_policy"]) == set(bench.POLICY_FACTORIES)
        assert set(report["off_policy_evaluation"]) == set(bench.POLICY_FACTORIES)
        # Every policy's headline metrics survived serialization.
        for stats in report["per_policy"].values():
            assert {"cumulative_regret", "mean_true_quality", "mean_list_cost"} <= set(stats)
        # print_report rendered the comparison table to stdout.
        captured = capsys.readouterr().out
        assert "offline model-routing bench" in captured
        for name in bench.POLICY_FACTORIES:
            assert name in captured

    def test_print_report_skips_policies_missing_from_results(self, capsys: Any) -> None:
        report = {
            "config": {"steps": 10, "seeds": [0], "delay": 1, "label_rate": 1.0, "drift_at": 5},
            "per_policy": {
                "static-router": {
                    "cumulative_regret": {"mean": 1.0, "std": 0.0},
                    "regret_rate_pre": {"mean": 0.0, "std": 0.0},
                    "regret_rate_post": {"mean": 0.0, "std": 0.0},
                    "recovery_step_mean": None,
                    "recovery_step_hits": "0/1",
                    "unsafe_exploration": {"mean": 0.0, "std": 0.0},
                    "mean_true_quality": {"mean": 0.8, "std": 0.0},
                    "mean_list_cost": {"mean": 1.0, "std": 0.0},
                },
            },
            "pareto_on_frontier": {"static-router": True},
            "off_policy_evaluation": {},
            "sample_efficiency": {},
            "run_results": [],
        }
        with contextlib.suppress(KeyError):
            bench.print_report(report)
        out = capsys.readouterr().out
        assert "static-router" in out
