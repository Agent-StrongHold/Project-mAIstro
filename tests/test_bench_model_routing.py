"""Tests for `scripts/bench_model_routing.py` (issue #914, epic #900 M8-B1).

The root suite is the coverage producer for `scripts/` (same arrangement as
`test_bench_working_memory.py`), so the benchmark's lines are scored by the
diff-coverage gate. Beyond coverage, these tests pin the properties that make
the benchmark's numbers trustworthy and comparable run-to-run:

- determinism: corpus, outcome table, and full report are stable;
- the structural claim the research note rests on: the shipped router's
  selection is invariant to the task descriptor (task-conditioning absent);
- policy seams: the baseline policy delegates to the real CostAwareRouter, and
  the conditioned policies respect reasoning/capacity constraints;
- metric hygiene: shares sum to 1, regret is non-negative, the oracle
  dominates every policy task-by-task;
- the leakage detector is decidable: outcome-blind policies produce zero
  violations, while the oracle — the one policy that reads the outcome table —
  trips it (positive control, so the check is not vacuous).

Everything runs offline at deliberately small scale (no network, no database)
so the suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_model_routing.py"

spec = importlib.util.spec_from_file_location("bench_model_routing", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


async def _registry(scenario: str = "all-available"):
    return await bench.build_registry(scenario)


def _easy_task() -> bench.Task:
    return bench.Task(
        task_id="chat-00000",
        task_type="chat",
        context_tokens=800,
        expected_output_tokens=200,
        tool_use=False,
        reasoning_required=False,
        latency_budget_ms=1500,
    )


def _reasoning_task() -> bench.Task:
    return bench.Task(
        task_id="planning-00000",
        task_type="planning",
        context_tokens=2_000,
        expected_output_tokens=800,
        tool_use=False,
        reasoning_required=True,
        latency_budget_ms=8000,
    )


class TestCorpus:
    def test_corpus_is_deterministic(self) -> None:
        first = bench.make_corpus("routing-bench-v1", 5)
        second = bench.make_corpus("routing-bench-v1", 5)
        assert [c.task for c in first] == [c.task for c in second]
        assert [c.difficulty for c in first] == [c.difficulty for c in second]
        # A different seed yields a different corpus.
        assert [c.task for c in bench.make_corpus("other", 5)] != [c.task for c in first]

    def test_corpus_covers_every_class_and_respects_bands(self) -> None:
        corpus = bench.make_corpus("routing-bench-v1", 20)
        by_class = dict.fromkeys(bench.CLASS_NAMES, 0)
        for case in corpus:
            by_class[case.task.task_type] += 1
            lo, hi = bench.CONTEXT_BANDS[case.task.task_type]
            assert lo <= case.task.context_tokens <= hi
            d_lo, d_hi = bench.TASK_CLASSES[case.task.task_type].difficulty
            assert d_lo <= case.difficulty <= d_hi
            assert case.task.context_tokens > 0 and case.task.expected_output_tokens > 0
        assert set(by_class.values()) == {20}

    def test_task_carries_no_outcome_fields(self) -> None:
        """Structural leakage guard: the policy-visible descriptor must not
        contain difficulty or any outcome field. If a field like this is ever
        added, policies can peek at the answer and every number is void."""
        names = {f.name for f in fields(bench.Task)}
        assert "difficulty" not in names
        assert not any("outcome" in n or "success" in n for n in names)

    def test_jittered_twin_is_bounded_and_keeps_outcomes(self) -> None:
        case = bench.make_task("routing-bench-v1", "summarization", 3)
        twin = bench.jittered_twin(case, "jitter-seed")
        assert twin.task.task_id == case.task.task_id
        assert twin.difficulty == case.difficulty  # outcome entry unchanged
        assert twin.task.tool_use == case.task.tool_use
        assert twin.task.reasoning_required == case.task.reasoning_required
        for attr in ("context_tokens", "expected_output_tokens"):
            base = getattr(case.task, attr)
            assert 0.94 <= getattr(twin.task, attr) / base <= 1.06


class TestOutcomeModel:
    async def test_outcome_is_deterministic_and_cost_comes_from_the_seam(self) -> None:
        registry = await _registry()
        models = await registry.list_models()
        case = bench.make_task("routing-bench-v1", "chat", 0)
        opus = next(m for m in models if m.name == "claude-3-opus")
        first = bench.simulate_outcome(case, opus, seed="s")
        again = bench.simulate_outcome(case, opus, seed="s")
        assert first == again
        # Cost comes from the real seam and is consistent with its inputs.
        expected = bench.compute_cost_cents(
            opus, min(case.task.context_tokens, opus.max_tokens), first.output_tokens
        )
        assert first.cost_cents == pytest.approx(expected)

    def test_capacity_overflow_is_a_hard_failure_costing_nothing(self) -> None:
        model = next(m for m in bench._catalog() if m.name == "gpt-3.5-turbo")  # max_tokens=4096
        case = bench.TaskCase(
            task=bench.Task(
                task_id="summarization-99999",
                task_type="summarization",
                context_tokens=30_000,
                expected_output_tokens=1_000,
                tool_use=False,
                reasoning_required=False,
                latency_budget_ms=5000,
            ),
            difficulty=0.4,
        )
        outcome = bench.simulate_outcome(case, model)
        assert outcome.success is False
        assert outcome.output_tokens == 0
        assert outcome.cost_cents == 0.0

    def test_escalation_shape_easy_tasks_do_not_need_powerful_models(self) -> None:
        """The simulator's central assumption, pinned: on easy tasks the fast
        tier succeeds about as often as the powerful tier; on hard tasks the
        fast tier falls off a cliff while the powerful tier holds."""
        easy = bench.TaskCase(
            task=_easy_task(),
            difficulty=0.2,
        )
        hard = bench.TaskCase(
            task=bench.Task(
                task_id="code_repair-00000",
                task_type="code_repair",
                context_tokens=3_000,
                expected_output_tokens=500,
                tool_use=False,
                reasoning_required=False,
                latency_budget_ms=8000,
            ),
            difficulty=0.9,
        )
        by_name = {m.name: m for m in bench._catalog()}
        runs = 400
        for case, fast_expect, powerful_expect in (
            (easy, (0.8, 1.0), (0.8, 1.0)),
            (hard, (0.0, 0.6), (0.85, 1.0)),
        ):
            rates = {}
            for name in ("gpt-3.5-turbo", "claude-3-opus"):
                wins = sum(
                    bench.simulate_outcome(case, by_name[name], seed=f"probe{i}").success
                    for i in range(runs)
                )
                rates[name] = wins / runs
            lo, hi = fast_expect
            assert lo <= rates["gpt-3.5-turbo"] <= hi, (case, rates)
            lo, hi = powerful_expect
            assert lo <= rates["claude-3-opus"] <= hi, (case, rates)
        # And the reasoning flag punishes non-reasoning models on the same task.
        reasoning = bench.TaskCase(
            task=bench.Task(
                task_id="planning-00001",
                task_type="planning",
                context_tokens=1_000,
                expected_output_tokens=300,
                tool_use=False,
                reasoning_required=True,
                latency_budget_ms=8000,
            ),
            difficulty=0.75,
        )

        def rate(name: str) -> float:
            wins = sum(
                bench.simulate_outcome(reasoning, by_name[name], seed=f"r{i}").success
                for i in range(runs)
            )
            return wins / runs

        assert rate("gpt-3.5-turbo") + 0.15 < rate("claude-3-opus")

    def test_utility_prizes_success_over_cheap_failure(self) -> None:
        good = bench.Outcome(
            success=True,
            latency_ms=1000.0,
            output_tokens=100,
            cost_cents=0.5,
            deadline_miss=False,
        )
        failed_free = bench.Outcome(
            success=False,
            latency_ms=0.0,
            output_tokens=0,
            cost_cents=0.0,
            deadline_miss=False,
        )
        assert good.utility > failed_free.utility


class TestPolicies:
    async def test_shipped_policy_delegates_to_the_real_router(self) -> None:
        registry = await _registry()
        router = bench.CostAwareRouter(registry)
        policy = bench.ShippedRouterPolicy(registry, router)
        task = _easy_task()
        call = await policy.route(task)
        assert call is not None and call.policy == "shipped-router"
        direct = await router.select(bench.RoutingTask(task_type=task.task_type), None)
        assert call.model_name == direct.name

    async def test_shipped_router_selection_ignores_the_task_descriptor(self) -> None:
        """The structural finding the whole benchmark is built on: the shipped
        router returns the same model for any task descriptor under the same
        budget. If this ever fails, the router is no longer static and the
        benchmark's baseline must be re-read."""
        registry = await _registry()
        router = bench.CostAwareRouter(registry)
        policy = bench.ShippedRouterPolicy(registry, router)
        selections = [await policy.select(task) for task in (_easy_task(), _reasoning_task())]
        assert {m.name for m in selections} == {selections[0].name}

    async def test_tier_conditioned_policy_respects_reasoning_and_capacity(self) -> None:
        registry = await _registry()
        policy = bench.TierConditionedPolicy(registry)
        # Reasoning-required task -> a powerful, reasoning-capable model.
        chosen = await policy.select(_reasoning_task())
        assert chosen.tier == "powerful" and chosen.reasoning_capable
        # Huge context -> a model whose window can actually hold it.
        big = bench.Task(
            task_id="summarization-00001",
            task_type="summarization",
            context_tokens=30_000,
            expected_output_tokens=1_000,
            tool_use=False,
            reasoning_required=False,
            latency_budget_ms=5000,
        )
        chosen = await policy.select(big)
        assert chosen.max_tokens >= big.context_tokens + big.expected_output_tokens
        # Easy small task -> a cheap tier, never powerful.
        chosen = await policy.select(_easy_task())
        assert chosen.tier in ("fast", "balanced")
        assert chosen.cost_per_1k_input < 0.01

    async def test_tier_conditioned_degrades_gracefully_when_opus_breaks(self) -> None:
        registry = await _registry("opus-degraded")
        policy = bench.TierConditionedPolicy(registry)
        chosen = await policy.select(_reasoning_task())
        assert chosen.name == "gpt-4-turbo"  # the remaining powerful tier

    async def test_budget_conditioned_reasoning_constraint_does_not_fall_back(self) -> None:
        """ADR-038 behavior worth knowing: capability-constrained selection
        through the shipped router raises rather than softening the constraint,
        so when the only reasoning-capable model is unavailable the route
        fails outright."""
        registry = await _registry("opus-degraded")
        router = bench.CostAwareRouter(registry)
        policy = bench.BudgetConditionedPolicy(registry, router)
        assert await policy.route(_reasoning_task()) is None
        assert policy.route_failures == 1

    async def test_oracle_picks_the_utility_argmax(self) -> None:
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 2)
        table = await bench.build_outcome_table(corpus, registry, "routing-bench-v1")
        oracle = bench.OraclePolicy(registry, table)
        case = corpus[0]
        chosen = await oracle.select(case.task)
        best = max(
            (m for m in await oracle.available()),
            key=lambda m: table[(case.task.task_id, m.name)].utility,
        )
        assert chosen.name == best.name


class TestMetrics:
    def test_percentile_edges(self) -> None:
        assert bench._percentile([], 50) == 0.0
        assert bench._percentile([7.0], 50) == 7.0
        assert bench._percentile([30.0, 10.0, 20.0], 50) == 20.0
        assert bench._percentile([10.0, 20.0, 30.0, 40.0], 95) == 40.0

    def test_hhi_bounds(self) -> None:
        assert bench._hhi({"a": 1.0}) == 1.0
        assert bench._hhi({"a": 0.5, "b": 0.5}) == 0.5
        assert bench._hhi({}) == 0.0

    async def test_score_policy_shares_sum_to_one_and_route_failures_price_in(
        self,
    ) -> None:
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 2)
        table = await bench.build_outcome_table(corpus, registry, "routing-bench-v1")
        models = await registry.list_models()
        metadata = {m.name: m for m in models}
        routed = [(corpus[0], "gpt-3.5-turbo"), (corpus[1], None)]
        report = bench.score_policy("x", routed, metadata, table, route_failures=1)
        # Shares are fractions of ALL tasks: a route failure leaves a visible
        # deficit instead of silently renormalizing the survivors.
        assert sum(report.model_shares.values()) == pytest.approx(0.5)
        assert sum(report.provider_shares.values()) == pytest.approx(0.5)
        assert report.model_shares == {"gpt-3.5-turbo": 0.5}
        assert report.route_failures == 1 and report.routed == 2
        assert report.success_rate == pytest.approx(0.5)
        # The failed route is priced as a miss: deadline_miss_rate counts it.
        assert report.deadline_miss_rate == pytest.approx(0.5)
        # With no failures the shares close over all tasks.
        clean = bench.score_policy(
            "y",
            [(corpus[0], "gpt-3.5-turbo"), (corpus[1], "gpt-3.5-turbo")],
            metadata,
            table,
            route_failures=0,
        )
        assert sum(clean.model_shares.values()) == pytest.approx(1.0)

    async def test_oracle_dominates_every_policy_task_by_task(self) -> None:
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 6)
        table = await bench.build_outcome_table(corpus, registry, "routing-bench-v1")
        router = bench.CostAwareRouter(registry)
        policies: list[bench.RoutingPolicy] = [
            bench.ShippedRouterPolicy(registry, router),
            bench.TierConditionedPolicy(registry),
        ]
        oracle = bench.OraclePolicy(registry, table)
        for case in corpus:
            oracle_util = table[(case.task.task_id, (await oracle.select(case.task)).name)].utility
            for policy in policies:
                call = await policy.route(case.task)
                assert call is not None
                util = table[(case.task.task_id, call.model_name)].utility
                assert oracle_util >= util - 1e-9


class TestLeakageAndStability:
    async def test_outcome_blind_policies_have_zero_leakage(self) -> None:
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 4)
        router = bench.CostAwareRouter(registry)
        for policy in (
            bench.ShippedRouterPolicy(registry, router),
            bench.TierConditionedPolicy(registry),
        ):
            assert await bench.leakage_audit(policy, corpus, registry, "seed") == 0

    async def test_leakage_detector_fires_on_the_oracle(self) -> None:
        """Positive control: the oracle reads the outcome table, so re-seeding
        outcomes must move its decisions. If this ever returns 0, the leakage
        audit can no longer detect an outcome-aware policy and is vacuous."""
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 10)
        table = await bench.build_outcome_table(corpus, registry, "routing-bench-v1")
        oracle = bench.OraclePolicy(registry, table)
        assert await bench.leakage_audit(oracle, corpus, registry, "routing-bench-v1") > 0

    async def test_stability_shipped_router_never_flips(self) -> None:
        registry = await _registry()
        corpus = bench.make_corpus("routing-bench-v1", 8)
        router = bench.CostAwareRouter(registry)
        policy = bench.ShippedRouterPolicy(registry, router)
        assert await bench.selection_flip_rate(policy, corpus, "jitter") == 0.0
        conditioned = bench.TierConditionedPolicy(registry)
        rate = await bench.selection_flip_rate(conditioned, corpus, "jitter")
        assert 0.0 <= rate <= 1.0

    async def test_instability_concentrates_at_capacity_boundaries(self) -> None:
        """A task sitting just above the balanced tier's largest window
        (16,300 + 300 demand vs gpt-4o-mini's 16,384) flips its selection
        exactly when the jittered context measurement drops the demand back
        under the window (opus -> gpt-4o-mini); a draw on the same task that
        stays above the boundary does not move it. Conditioned routing's
        instability is bounded and located at the boundary — the property the
        research note reports as a 1.1% corpus-level flip rate. Seeds are
        pinned draws: with seed 'j3' the ±5% context jitter lands below the
        boundary (jitter factor 0.9775), with 'jitter' above (1.0179)."""
        registry = await _registry()

        def case(context: int, task_id: str) -> bench.TaskCase:
            return bench.TaskCase(
                task=bench.Task(
                    task_id=task_id,
                    task_type="summarization",
                    context_tokens=context,
                    expected_output_tokens=300,
                    tool_use=False,
                    reasoning_required=False,
                    latency_budget_ms=5000,
                ),
                difficulty=0.4,
            )

        boundary = case(16_300, "summarization-90001")  # demand 16_600 > 16_384
        inside = case(8_000, "summarization-90002")  # demand 8_300, mid-band
        policy = bench.TierConditionedPolicy(registry)
        assert await bench.selection_flip_rate(policy, [boundary], "j3") == 1.0
        # Same task, jitter draw stays above the boundary: stable.
        assert await bench.selection_flip_rate(policy, [boundary], "jitter") == 0.0
        assert await bench.selection_flip_rate(policy, [inside], "j3") == 0.0


class TestRunBenchmark:
    async def test_report_shape_is_stable(self) -> None:
        report = await bench.run_benchmark(seed="shape-seed", tasks_per_class=2)
        assert set(report) >= {
            "benchmark",
            "issue",
            "epic",
            "seam",
            "config",
            "policies",
            "comparisons_vs_shipped",
            "stability_flip_rate_under_jitter",
            "leakage_violations",
            "leakage_positive_control_oracle_changes",
        }
        names = [p["policy"] for p in report["policies"]]  # type: ignore[index]
        assert names == [
            "shipped-router",
            "static-cheap",
            "budget-conditioned",
            "tier-conditioned",
            "oracle",
        ]
        assert report["issue"] == "914" and report["epic"] == "900"  # type: ignore[index]
        assert set(report["leakage_violations"]) == set(names[:-1])  # type: ignore[arg-type]
        assert all(
            v == 0
            for v in report["leakage_violations"].values()  # type: ignore[attr-defined]
        )
        assert report["leakage_positive_control_oracle_changes"] > 0  # type: ignore[operator]
        assert set(report["comparisons_vs_shipped"]) == set(names[1:])  # type: ignore[arg-type]
        # Every comparison row carries the metric deltas the issue names.
        for row in report["comparisons_vs_shipped"].values():  # type: ignore[attr-defined]
            assert set(row) == {
                "delta_success_rate",
                "delta_cost_per_task_cents",
                "delta_latency_p95_ms",
                "delta_mean_utility",
                "regret_vs_oracle",
            }
            assert row["regret_vs_oracle"] >= 0.0
        json.dumps(report)  # must round-trip

    async def test_report_is_deterministic_run_to_run(self) -> None:
        first = await bench.run_benchmark(seed="det", tasks_per_class=3)
        second = await bench.run_benchmark(seed="det", tasks_per_class=3)
        assert first == second

    async def test_unknown_scenario_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown scenario"):
            await bench.build_registry("bogus")

    async def test_conditioned_policies_dominate_on_hard_classes(self) -> None:
        """The hypothesis signal, pinned at small scale: task-conditioned
        selection must not lose success rate against the static router, and
        must beat it on the hard classes where the static router leaves
        success on the floor."""
        report = await bench.run_benchmark(seed="dom", tasks_per_class=6)
        policies = {p["policy"]: p for p in report["policies"]}  # type: ignore[index]
        shipped = policies["shipped-router"]
        for name in ("budget-conditioned", "tier-conditioned"):
            assert policies[name]["success_rate"] >= shipped["success_rate"]
            assert policies[name]["mean_utility"] > shipped["mean_utility"]
        oracle = policies["oracle"]
        for p in policies.values():
            assert oracle["mean_utility"] >= p["mean_utility"] - 1e-9


class TestCli:
    def test_main_writes_json_and_exits_zero(self, tmp_path: Path) -> None:
        out = tmp_path / "routing-bench.json"
        rc = bench.main(["--tasks-per-class", "2", "--output", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["benchmark"] == "task-conditioned-model-routing"
        assert len(payload["policies"]) == 5

    def test_main_rejects_unknown_scenario(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            bench.main(["--scenario", "nope"])
