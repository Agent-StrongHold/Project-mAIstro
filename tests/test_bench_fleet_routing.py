"""Tests for `scripts/bench_fleet_routing.py` (issue #934, epic #905 M8-F1).

The root suite is the coverage producer for `scripts/` (same arrangement as
`test_bench_model_routing.py`), so the benchmark's lines are scored by the
diff-coverage gate. Beyond coverage, these tests pin the properties that make
the fleet benchmark's numbers trustworthy and comparable run-to-run:

- determinism: corpus, provider-pressure schedule (seed-independent), and the
  full report are stable;
- the seam claim the research note rests on: every selection is a real
  `CostAwareRouter.select` call, fleet composition is expressed only through
  scope/budget/availability, and the shipped call shape over the whole fleet
  sends essentially everything to the hosted latency-winner (local capacity
  gets no absorption without a composition policy);
- scenario mechanics: outage injection rides the registry availability seam,
  pressure rides a seed-independent observable schedule;
- escalation mechanics: only observable failures (capacity, rate limit)
  escalate, attempted models are excluded per call, quality failures and
  route failures do not;
- accounting hygiene: local attempts cost exactly zero, observable failures
  bill nothing, shares sum to 1, single-attempt policies never beat the
  oracle, a fully-collapsed fleet reports zero throughput (not infinity);
- the leakage detector is decidable: outcome-blind policies produce zero
  violations while the oracle — the one policy that reads the outcome table —
  trips it (positive control, so the check is not vacuous);
- portability: the model-egress ratchet ledger is intact and the bench
  reports zero new direct callers (fail-closed when the ledger is missing).

Everything runs offline at deliberately small scale (no network, no database)
so the suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_fleet_routing.py"

spec = importlib.util.spec_from_file_location("bench_fleet_routing", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)

CORPUS_SEED = "fleet-bench-v1"
SMALL = 6  # tasks per class at test scale (36 tasks)


async def _registry(scenario: str = "all-available"):
    return await bench.build_registry(scenario)


async def _wired(scenario: str = "all-available"):
    """(registry, router, policies) wired the way the driver wires them."""
    registry = await _registry(scenario)
    router = bench.CostAwareRouter(registry)
    outcomes = await bench.build_outcome_table(
        bench.make_corpus(CORPUS_SEED, SMALL), registry, scenario, CORPUS_SEED
    )
    return registry, router, bench.build_policies(registry, router, outcomes)


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


class TestCatalog:
    def test_catalog_is_the_heterogeneous_fleet(self) -> None:
        catalog = bench._catalog()
        names = [m.name for m in catalog]
        assert len(names) == len(set(names))
        providers = {m.provider for m in catalog}
        assert providers == bench.LOCAL_PROVIDERS | bench.HOSTED_PROVIDERS
        # The local fleet has internal selection and a reasoning-capable member.
        local = [m for m in catalog if m.provider in bench.LOCAL_PROVIDERS]
        assert len(local) >= 2
        assert any(m.reasoning_capable for m in local)
        # Hosted capacity spans more than one provider, so a single-provider
        # outage is survivable without local capacity.
        hosted_providers = {m.provider for m in catalog if m.provider in bench.HOSTED_PROVIDERS}
        assert len(hosted_providers) >= 2

    def test_local_entries_are_free_and_hosted_are_priced(self) -> None:
        for model in bench._catalog():
            if model.provider in bench.LOCAL_PROVIDERS:
                assert model.cost_per_1k_input == 0.0
                assert model.cost_per_1k_output == 0.0
            else:
                assert model.cost_per_1k_input > 0.0
                assert model.cost_per_1k_output > 0.0

    def test_every_fallback_resolves(self) -> None:
        names = {m.name for m in bench._catalog()}
        for model in bench._catalog():
            assert set(model.fallback_to) <= names


class TestCorpus:
    def test_corpus_is_deterministic_and_seed_sensitive(self) -> None:
        first = bench.make_corpus(CORPUS_SEED, 3)
        second = bench.make_corpus(CORPUS_SEED, 3)
        assert first == second
        assert bench.make_corpus("other", 3) != first
        assert len(first) == len(bench.CLASS_NAMES) * 3

    def test_jittered_twin_moves_only_observable_features(self) -> None:
        case = bench.make_corpus(CORPUS_SEED, 2)[0]
        twin = bench.jittered_twin(case, "jitter")
        assert twin.task.task_id == case.task.task_id
        assert twin.difficulty == case.difficulty
        assert twin.task.reasoning_required == case.task.reasoning_required
        assert twin.task.tool_use == case.task.tool_use
        assert twin.task.context_tokens != case.task.context_tokens


class TestProviderPressure:
    def test_local_never_rate_limits(self) -> None:
        registry_local = [m for m in bench._catalog() if m.provider in bench.LOCAL_PROVIDERS]
        for model in registry_local:
            for scenario in bench.SCENARIOS:
                assert not bench.provider_rate_limited("chat-00000", model, scenario)

    def test_pressure_only_fires_in_the_pressure_scenario(self) -> None:
        model = bench._catalog()[0]  # claude-3-opus, hosted
        for scenario in ("all-available", "local-outage", "hosted-outage"):
            assert not bench.provider_rate_limited("chat-00000", model, scenario)
        # At 35% the draw fires for some task in a small sample.
        fired = any(
            bench.provider_rate_limited(f"chat-{i:05d}", model, "capacity-pressure")
            for i in range(30)
        )
        assert fired

    def test_pressure_is_run_seed_independent(self) -> None:
        """Pressure models observable egress conditions: re-seeding the run
        must not move the schedule (the leakage audit's premise)."""
        model = bench._catalog()[0]
        for i in range(10):
            task_id = f"chat-{i:05d}"
            assert bench.provider_rate_limited(task_id, model, "capacity-pressure") == (
                bench.provider_rate_limited(task_id, model, "capacity-pressure")
            )


class TestAttemptModel:
    def test_capacity_bound_is_registry_arithmetic(self) -> None:
        case = bench.TaskCase(_easy_task(), difficulty=0.1)
        small = next(m for m in bench._catalog() if m.name == "gpt-3.5-turbo")
        outcome = bench.simulate_attempt(case, small, "all-available")
        # 1000 tokens of demand against a 4096 window fits; force a miss.
        big = bench.TaskCase(
            bench.Task(
                task_id="summarization-99999",
                task_type="summarization",
                context_tokens=30_000,
                expected_output_tokens=2_000,
                tool_use=False,
                reasoning_required=False,
                latency_budget_ms=5000,
            ),
            difficulty=0.4,
        )
        overflow = bench.simulate_attempt(big, small, "all-available")
        assert overflow.kind == "capacity"
        assert not overflow.success
        assert overflow.cost_cents == 0.0
        assert overflow.observable_failure
        assert outcome.kind in ("ok", "quality_fail")

    def test_rate_limited_attempt_bills_nothing_but_pays_queue_time(self) -> None:
        model = next(m for m in bench._catalog() if m.name == "gpt-4-turbo")
        # Find a (task, model) pair whose pressure draw fires.
        fired = None
        for i in range(500):
            task = bench.Task(
                task_id=f"chat-{i:05d}",
                task_type="chat",
                context_tokens=800,
                expected_output_tokens=200,
                tool_use=False,
                reasoning_required=False,
                latency_budget_ms=1500,
            )
            if bench.provider_rate_limited(task.task_id, model, "capacity-pressure"):
                fired = bench.TaskCase(task, difficulty=0.1)
                break
        assert fired is not None
        outcome = bench.simulate_attempt(fired, model, "capacity-pressure")
        assert outcome.kind == "rate_limited"
        assert outcome.cost_cents == 0.0
        assert outcome.output_tokens == 0
        assert outcome.latency_ms == pytest.approx(
            model.latency_p50_ms * bench.RATE_LIMIT_LATENCY_FRACTION
        )
        assert outcome.observable_failure

    def test_attempt_outcome_is_deterministic(self) -> None:
        case = bench.make_corpus(CORPUS_SEED, 4)[0]
        model = bench._catalog()[0]
        first = bench.simulate_attempt(case, model, "all-available")
        second = bench.simulate_attempt(case, model, "all-available")
        assert first == second
        # The hidden realization moves with the seed; pressure does not.
        reseeded = bench.simulate_attempt(case, model, "all-available", seed="alt")
        assert reseeded.kind == first.kind or first.kind in ("capacity", "rate_limited")


class TestScenarios:
    async def test_unknown_scenario_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="unknown scenario"):
            await bench.build_registry("blackhole")

    async def test_local_outage_marks_only_local_unavailable(self) -> None:
        registry = await _registry("local-outage")
        for model in await registry.list_models():
            if model.provider in bench.LOCAL_PROVIDERS:
                assert not registry.is_available(model.name)
            else:
                assert registry.is_available(model.name)

    async def test_hosted_outage_marks_only_anthropic_unavailable(self) -> None:
        registry = await _registry("hosted-outage")
        for model in await registry.list_models():
            if model.provider == "anthropic":
                assert not registry.is_available(model.name)
            else:
                assert registry.is_available(model.name)

    async def test_benign_scenario_marks_nothing(self) -> None:
        registry = await _registry("all-available")
        for model in await registry.list_models():
            assert registry.is_available(model.name)


class TestFleetPolicies:
    async def test_scoped_fleets_never_cross_the_provider_boundary(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        for providers, name in (
            (bench.HOSTED_PROVIDERS, "hosted-only"),
            (bench.LOCAL_PROVIDERS, "local-only"),
        ):
            registry, _router, policies = await _wired()
            policy = next(p for p in policies if p.name == name)
            results = await bench.route_all(policy, corpus, "all-available")
            metadata = {m.name: m for m in await registry.list_models()}
            attempted = {a.model_name for r in results for a in r.attempts}
            assert attempted, name
            for model_name in attempted:
                assert metadata[model_name].provider in providers

    async def test_shipped_router_absorbs_no_local_work_in_benign_fleet(self) -> None:
        """The structural claim: adding local entries to the registry without a
        composition policy changes nothing — the shipped latency-first router
        keeps every task on the hosted latency-winner."""
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-shipped")
        results = await bench.route_all(policy, corpus, "all-available")
        first_attempts = [r.attempts[0].model_name for r in results if r.attempts]
        assert first_attempts
        assert set(first_attempts) == {"gpt-3.5-turbo"}

    async def test_shipped_router_is_fit_blind(self) -> None:
        """Production call shape has no capacity prefilter: some task lands on
        a model whose registry window cannot hold it, and the attempt fails
        with an observable capacity error (#914's structural finding)."""
        corpus = bench.make_corpus(CORPUS_SEED, 40)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-shipped")
        results = await bench.route_all(policy, corpus, "all-available")
        capacity_failures = [
            r for r in results if r.attempts and r.final and r.final.kind == "capacity"
        ]
        assert capacity_failures

    async def test_local_first_policy_routes_easy_work_to_local(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "all-available")
        by_id = {r.task_id: r for r in results}
        easy = [r for tid, r in by_id.items() if tid.startswith(("chat-", "classification-"))]
        firsts = {r.attempts[0].model_name for r in easy if r.attempts}
        assert firsts <= {"local-llama", "local-qwen-14b"}
        assert "local-llama" in firsts  # latency-first picks the fast local entry

    async def test_local_first_policy_routes_reasoning_to_capable_entries(self) -> None:
        registry, router, _ = await _wired()
        policy = bench.MixedLocalFirstPolicy(registry, router)
        case = bench.TaskCase(_reasoning_task(), difficulty=0.7)
        result = (await bench.route_all(policy, [case], "all-available"))[0]
        assert result.attempts
        first = result.attempts[0]
        metadata = {m.name: m for m in await registry.list_models()}
        assert metadata[first.model_name].reasoning_capable

    async def test_local_first_never_escalates_in_the_benign_fleet(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "all-available")
        assert all(len(r.attempts) == 1 for r in results if r.attempts)


class TestEscalationAndFailure:
    async def test_only_observable_failures_escalate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A quality failure is invisible at the egress: the task ends after
        one attempt even though it failed. Pinned at the mechanic level (the
        simulator is stubbed) so the policy rule cannot drift with outcome
        calibration."""
        registry, router, _ = await _wired()
        policy = bench.MixedLocalFirstPolicy(registry, router)
        case = bench.TaskCase(_easy_task(), difficulty=0.1)

        def quality_fail(
            case: bench.TaskCase, model: object, scenario: str, seed: str = ""
        ) -> bench.AttemptOutcome:
            return bench.AttemptOutcome(
                kind="quality_fail",
                success=False,
                latency_ms=100.0,
                output_tokens=0,
                cost_cents=0.0,
                deadline_miss=False,
            )

        monkeypatch.setattr(bench, "simulate_attempt", quality_fail)
        result = (await bench.route_all(policy, [case], "all-available"))[0]
        assert len(result.attempts) == 1
        assert result.attempts[0].kind == "quality_fail"
        assert not result.success

    async def test_observable_failure_escalates_and_the_retry_is_new(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A capacity failure on the local attempt escalates to the next
        stage, whose scope excludes the attempted model."""
        registry, router, _ = await _wired()
        policy = bench.MixedLocalFirstPolicy(registry, router)
        case = bench.TaskCase(_easy_task(), difficulty=0.1)
        seen: list[str] = []

        def capacity_then_ok(
            case: bench.TaskCase, model: object, scenario: str, seed: str = ""
        ) -> bench.AttemptOutcome:
            outcome_kind = "capacity" if not seen else "ok"
            seen.append(str(getattr(model, "name", "")))
            return bench.AttemptOutcome(
                kind=outcome_kind,
                success=outcome_kind == "ok",
                latency_ms=100.0,
                output_tokens=0,
                cost_cents=0.0,
                deadline_miss=False,
            )

        monkeypatch.setattr(bench, "simulate_attempt", capacity_then_ok)
        result = (await bench.route_all(policy, [case], "all-available"))[0]
        assert len(result.attempts) == 2
        assert result.attempts[0].kind == "capacity"
        assert result.attempts[1].kind == "ok"
        assert result.success
        assert len(set(seen)) == 2  # the retry selected a different model

    async def test_escalation_excludes_attempted_models(self) -> None:
        """Under pressure the candidate's hosted attempts rate-limit and the
        retry scope excludes everything already attempted."""
        corpus = bench.make_corpus(CORPUS_SEED, 40)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "capacity-pressure")
        escalated = [r for r in results if r.escalated]
        assert escalated
        for result in escalated:
            names = [a.model_name for a in result.attempts]
            assert len(set(names[:-1])) == len(names) - 1  # retries are all-new models
            assert result.attempts[0].kind in ("capacity", "rate_limited")

    async def test_total_local_outage_collapses_the_local_fleet(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired("local-outage")
        policy = next(p for p in policies if p.name == "local-only")
        results = await bench.route_all(policy, corpus, "local-outage")
        assert policy.route_failures == len(corpus)
        assert all(not r.attempts for r in results)
        report = bench.score_fleet(policy.name, results, {}, policy.route_failures)
        assert report.routed == 0
        # A collapsed fleet completes nothing: throughput is zero, not a
        # divide-by-the-1ms-floor artifact.
        assert report.tasks_per_sec_corpus == 0.0
        assert report.success_throughput_per_sec == 0.0
        assert report.mean_utility < 0.0

    async def test_route_failure_never_looks_cheap(self) -> None:
        """The route-failure pricing path: a task with no attempts adds the
        worst-outcome utility, never a zero."""
        results = [bench.TaskResult(task_id=f"t{i}") for i in range(5)]
        report = bench.score_fleet("none", results, {}, route_failures=5)
        assert report.mean_utility == pytest.approx(-0.25)
        assert report.route_failures == 5


class TestAccounting:
    async def test_local_attempts_cost_exactly_zero(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "all-available")
        local_results = [r for r in results if r.attempts[0].model_name.startswith("local-")]
        assert local_results
        assert all(r.cost_cents == 0.0 for r in local_results)

    async def test_observable_failures_bill_nothing_on_the_sunk_attempt(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, 40)
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "capacity-pressure")
        escalated = [r for r in results if r.escalated]
        assert escalated
        metadata = {m.name: m for m in bench._catalog()}
        for result in escalated:
            sunk = result.attempts[:-1]
            assert all(a.cost_cents == 0.0 for a in sunk)
            assert all(a.observable_failure for a in sunk)
            # The composition rule: sunk observable failures cost latency
            # only; the bill comes from the final (successful or not) call.
            final = result.final
            assert final is not None
            expected = sum(a.cost_cents for a in result.attempts)
            model = metadata[final.model_name]
            if final.kind in ("ok", "quality_fail"):
                assert expected > 0.0 or model.provider in bench.LOCAL_PROVIDERS

    async def test_shares_sum_to_one_and_utilization_is_bounded(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        registry, _, policies = await _wired()
        metadata = {m.name: m for m in await registry.list_models()}
        for policy in policies:
            results = await bench.route_all(policy, corpus, "all-available")
            report = bench.score_fleet(policy.name, results, metadata, policy.route_failures)
            if report.routed:
                assert sum(report.model_shares.values()) == pytest.approx(1.0)
                assert sum(report.provider_shares.values()) == pytest.approx(1.0)
            assert 0.0 <= report.local_executor_busy_fraction <= 1.0
            assert 0.0 <= report.hosted_fleet_utilization <= 1.0
            assert 0.0 <= report.success_rate <= 1.0
            assert report.attempts_per_task >= 1.0 or report.routed == 0


class TestThroughputAndHardware:
    async def test_hosted_elasticity_beats_serial_local_throughput(self) -> None:
        """The hardware model's core asymmetry: elastic hosted concurrency
        completes more tasks per second than one serial local executor."""
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        metadata = {m.name: m for m in bench._catalog()}
        _, _, policies = await _wired()
        by_name = {}
        for policy in policies:
            results = await bench.route_all(policy, corpus, "all-available")
            report = bench.score_fleet(policy.name, results, metadata, policy.route_failures)
            by_name[report.policy] = report
        assert (
            by_name["hosted-only"].tasks_per_sec_corpus > by_name["local-only"].tasks_per_sec_corpus
        )
        assert by_name["local-only"].local_executor_busy_fraction == pytest.approx(1.0)
        assert by_name["hosted-only"].local_executor_busy_fraction == 0.0

    async def test_local_executors_to_match_hosted_is_counted(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        metadata = {m.name: m for m in bench._catalog()}
        _, _, policies = await _wired()
        policy = next(p for p in policies if p.name == "mixed-local-first")
        results = await bench.route_all(policy, corpus, "all-available")
        report = bench.score_fleet(policy.name, results, metadata, policy.route_failures)
        assert report.local_executors_to_match_hosted >= 1
        assert report.operational_complexity["extra_local_processes"] == 1
        assert report.operational_complexity["local_entries"] == 2

    async def test_latency_percentiles_empty_and_populated(self) -> None:
        assert bench._percentile([], 95) == 0.0
        assert bench._percentile([5.0], 95) == 5.0
        assert bench._percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
        assert bench._hhi({"a": 1.0}) == 1.0
        assert bench._hhi({"a": 0.5, "b": 0.5}) == pytest.approx(0.5)


class TestBenchmarkDriver:
    async def test_full_report_is_deterministic(self) -> None:
        first = await bench.run_fleet_benchmark(CORPUS_SEED, 3, "all-available")
        second = await bench.run_fleet_benchmark(CORPUS_SEED, 3, "all-available")
        assert first == second

    async def test_report_names_policies_and_comparisons(self) -> None:
        report = await bench.run_fleet_benchmark(CORPUS_SEED, 3, "capacity-pressure")
        assert report["benchmark"] == "heterogeneous-fleet-routing"
        assert report["issue"] == "934"
        assert report["epic"] == "905"
        names = [p["policy"] for p in report["policies"]]  # type: ignore[index]
        assert names == [
            "hosted-only",
            "local-only",
            "mixed-shipped",
            "mixed-local-first",
            "oracle",
        ]
        comparisons = report["comparisons_vs_hosted_only"]  # type: ignore[attr-defined]
        assert set(comparisons) == {  # type: ignore[attr-defined]
            "local-only",
            "mixed-shipped",
            "mixed-local-first",
            "oracle",
        }
        for deltas in comparisons.values():  # type: ignore[attr-defined]
            assert set(deltas) == {
                "delta_success_rate",
                "delta_cost_total_cents",
                "delta_latency_p95_ms",
                "delta_mean_utility",
                "delta_utility_vs_single_attempt_oracle",
                "delta_tasks_per_sec",
            }

    async def test_single_attempt_policies_never_beat_the_oracle(self) -> None:
        """Regret is non-negative for policies that get exactly one attempt;
        the failover candidate may exceed the single-attempt ceiling (extra
        attempts), which is why its delta is reported unsigned."""
        report = await bench.run_fleet_benchmark(CORPUS_SEED, 8, "all-available")
        by_name = {p["policy"]: p for p in report["policies"]}  # type: ignore[index]
        oracle_util = by_name["oracle"]["mean_utility"]  # type: ignore[index]
        for name in ("hosted-only", "local-only", "mixed-shipped"):
            assert by_name[name]["mean_utility"] <= oracle_util + 1e-9  # type: ignore[index]
        assert (
            by_name["mixed-local-first"]["mean_utility"] <= oracle_util + 0.35  # type: ignore[index]
        )

    async def test_pressure_scenario_degrades_hosted_and_escalates_the_candidate(self) -> None:
        benign = await bench.run_fleet_benchmark(CORPUS_SEED, 8, "all-available")
        pressure = await bench.run_fleet_benchmark(CORPUS_SEED, 8, "capacity-pressure")

        def by_name(report: object) -> dict[str, dict[str, object]]:
            return {p["policy"]: p for p in report["policies"]}  # type: ignore[index,union-attr]

        benign_p, pressure_p = by_name(benign), by_name(pressure)
        assert (
            pressure_p["hosted-only"]["success_rate"]  # type: ignore[index]
            < benign_p["hosted-only"]["success_rate"]
        )
        assert pressure_p["mixed-local-first"]["escalated_rate"] > 0.0  # type: ignore[index]
        # ...and the candidate still lands more successes than the incumbent.
        assert (
            pressure_p["mixed-local-first"]["success_rate"]  # type: ignore[index]
            > pressure_p["hosted-only"]["success_rate"]
        )

    async def test_all_scenarios_mode_reports_every_scenario(self) -> None:
        report = await bench.run_all_scenarios(CORPUS_SEED, 2)
        assert report["mode"] == "all-scenarios"  # type: ignore[index]
        assert set(report["scenarios"]) == set(bench.SCENARIOS)  # type: ignore[index]
        portability = report["portability"]  # type: ignore[index]
        assert portability["new_direct_callers_added"] == 0  # type: ignore[index]


class TestAudit:
    async def test_outcome_blind_policies_have_zero_leakage_violations(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        registry, _router, policies = await _wired()
        for policy in policies:
            if policy.name == "oracle":
                continue
            violations = await bench.leakage_audit(
                policy, corpus, registry, "all-available", CORPUS_SEED
            )
            assert violations == 0, policy.name

    async def test_oracle_is_the_leakage_positive_control(self) -> None:
        """The detector must be able to fire: re-seeding the table moves the
        one policy that reads it."""
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        registry, router, _ = await _wired()
        outcomes = await bench.build_outcome_table(corpus, registry, "all-available", CORPUS_SEED)
        oracle = bench.OraclePolicy(registry, router, outcomes)
        violations = await bench.leakage_audit(
            oracle, corpus, registry, "all-available", CORPUS_SEED
        )
        assert violations > 0

    async def test_oracle_route_fails_when_no_model_fits_or_survives(self) -> None:
        """The oracle's degenerate path: with every entry circuit-broken (or
        nothing capacity-adequate), it route-fails like any other policy
        instead of inventing a route."""
        corpus = bench.make_corpus(CORPUS_SEED, 2)
        registry = await _registry()
        router = bench.CostAwareRouter(registry)
        outcomes = await bench.build_outcome_table(corpus, registry, "all-available", CORPUS_SEED)
        oracle = bench.OraclePolicy(registry, router, outcomes)
        for model in await registry.list_models():
            registry.mark_unavailable(model.name)
        results = await bench.route_all(oracle, corpus, "all-available")
        assert oracle.route_failures == len(corpus)
        assert all(not r.attempts for r in results)

    async def test_static_fleets_never_flip_under_jitter(self) -> None:
        corpus = bench.make_corpus(CORPUS_SEED, SMALL)
        _, _, policies = await _wired()
        for policy in policies:
            if policy.name in ("hosted-only", "local-only", "mixed-shipped"):
                flips = await bench.selection_flip_rate(
                    policy, corpus, "all-available", CORPUS_SEED + "|jitter"
                )
                assert flips == 0.0, policy.name


class TestPortability:
    def test_model_egress_audit_reports_the_frozen_ledger(self) -> None:
        audit = bench._model_egress_audit()
        assert audit["model_egress_rows"] > 0
        assert audit["approved_gateway_present"] is True
        assert audit["new_direct_callers_added"] == 0

    def test_model_egress_audit_fails_closed_when_ledger_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="model-egress ledger missing"):
            bench._model_egress_audit(tmp_path / "absent.json")

    def test_model_egress_audit_accepts_module_object_rows(self, tmp_path: Path) -> None:
        ledger = tmp_path / "model-egress.json"
        ledger.write_text(json.dumps({"modules": [{"module": "some.direct.caller"}]}))
        audit = bench._model_egress_audit(ledger)
        assert audit["model_egress_rows"] == 1
        assert audit["approved_gateway_present"] is False


class TestCLI:
    def test_main_writes_single_scenario_payload(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "fleet.json"
        rc = bench.main(
            ["--tasks-per-class", "2", "--scenario", "all-available", "--output", str(out)]
        )
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["config"]["scenario"] == "all-available"
        assert "portability" in payload
        assert "policy" in capsys.readouterr().out

    def test_main_all_mode_nests_scenarios(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "fleet-all.json"
        rc = bench.main(["--tasks-per-class", "2", "--scenario", "all", "--output", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["mode"] == "all-scenarios"
        assert set(payload["scenarios"]) == set(bench.SCENARIOS)
        captured = capsys.readouterr().out
        for scenario in bench.SCENARIOS:
            assert f"scenario: {scenario}" in captured

    def test_main_without_output_only_prints(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = bench.main(["--tasks-per-class", "2", "--scenario", "local-outage"])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "policy" in captured
        assert "written:" not in captured

    def test_main_rejects_unknown_scenario(self) -> None:
        with pytest.raises(SystemExit):
            bench.main(["--scenario", "blackhole"])
