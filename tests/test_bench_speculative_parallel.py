"""Tests for `scripts/bench_speculative_parallel.py` (issue #917, epic #900).

The root suite is the coverage producer for `scripts/`, so the benchmark's
changed lines are scored by the diff-coverage gate — a script with zero tests
measures 0% and reds the gate. Beyond the measurement, these tests pin the
properties the recorded numbers depend on:

- the candidate chain is the canonical cost-aware router's fallback chain, not
  a hand-rolled list;
- the outcome schedule is deterministic and strategy-independent (common
  random numbers), with correlated outages wired by provider;
- every strategy path is exact under a pinned physics table — serial
  escalation, first-acceptable early stop with real cancellation (losers end
  as UNKNOWN Invocations), noisy-verifier selection with counted selection
  error — including the degenerate nobody-acceptable paths;
- the Invocation ledger records every physical candidate call exactly once:
  duplicates are measured, never hidden;
- end-to-end runs are byte-identical across executions and the published JSON
  payload has a stable shape.

Everything runs offline at a deliberately small scale (no network, in-memory
stores) so the suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_speculative_parallel.py"

spec = importlib.util.spec_from_file_location("bench_speculative_parallel", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)

SCALE = 0.004
MODEL_NAMES = [spec.name for spec in bench.DIVERSE_CATALOG]
QUICK, BALANCED, STRONG = MODEL_NAMES


def _outcome(**over: Any) -> bench.Outcome:
    values: dict[str, Any] = {
        "latency_ms": 1000.0,
        "acceptable": True,
        "transient_failure": False,
        "true_score": 0.8,
        "noisy_score": 0.8,
    }
    values.update(over)
    return bench.Outcome(**values)


def _schedule(table: dict[tuple[int, str], bench.Outcome]) -> Callable[[int, str], bench.Outcome]:
    def outcome(task: int, model: str) -> bench.Outcome:
        return table.get((task, model), _outcome())

    return outcome


async def _drive(
    strategy_fn: Callable[..., Any],
    table: dict[tuple[int, str], bench.Outcome],
    *,
    chain: list[str] | None = None,
    task: int = 0,
    label: str = "drv",
) -> tuple[bench.TaskOutcome, list[bench.PhysicalCall], dict[str, int]]:
    """Run one strategy function against the real governed seam with pinned
    physics, then settle billing and audit the Invocation ledger."""

    specs = bench.DIVERSE_CATALOG
    registry = bench.build_registry(specs)
    router = bench.CostAwareRouter(registry)
    outcome_of = _schedule(table)
    gateway = bench.SimulatedGateway(specs, outcome_of, label=label, scale=SCALE)
    bench.set_test_transport(gateway.transport())
    try:
        effects = bench._effects()
        egress = bench.ModelChatEgress(
            effects, registry=registry, router=router, endpoint=bench.ENDPOINT
        )
        bindings = {s.name: bench._binding(s.name) for s in specs}
        models = [s.name for s in specs]
        outcome = await strategy_fn(
            egress, bindings, chain if chain is not None else models, outcome_of, label, task
        )
        counts = await bench.count_invocations(effects, bindings, gateway.records_for(task), label)
    finally:
        bench.set_test_transport(None)
    bench._settle_billing(gateway.records_for(task), outcome)
    return outcome, gateway.records_for(task), counts


class TestCatalogAndRegistry:
    def test_serial_chain_is_the_canonical_router_fallback_chain(self) -> None:
        registry = bench.build_registry(bench.DIVERSE_CATALOG)
        router = bench.CostAwareRouter(registry)
        chain = asyncio.run(router.fallback_chain(bench.CHAIN_HEAD))
        assert [m.name for m in chain] == MODEL_NAMES
        # The canonical chain is ordered cheapest-latency-first (ADR-079),
        # which is exactly the serial-fallback baseline the benchmark claims.
        assert [m.latency_p50_ms for m in chain] == sorted(m.latency_p50_ms for m in chain)

    def test_same_topology_collapses_providers_keeps_physics(self) -> None:
        same = bench.catalog_for("same")
        assert [s.name for s in same] == MODEL_NAMES
        assert {s.provider for s in same} == {"alpha"}
        assert [s.latency_ms for s in same] == [s.latency_ms for s in bench.DIVERSE_CATALOG]
        with pytest.raises(ValueError, match="unknown topology"):
            bench.catalog_for("holo")

    def test_single_strong_pins_the_strongest_model(self) -> None:
        summary = asyncio.run(
            bench.run_strategy("single-strong", "diverse", 1, seed=1, scale=SCALE)
        )
        assert summary.physical_calls == 1
        # strong-405b jittered around 5200ms
        assert 3100 < summary.p50_ms < 7300


class TestOutcomeSchedule:
    def test_schedule_is_deterministic_and_strategy_independent(self) -> None:
        first = bench.make_outcome_schedule(917, bench.DIVERSE_CATALOG)
        second = bench.make_outcome_schedule(917, bench.DIVERSE_CATALOG)
        for task in range(14):
            for model in MODEL_NAMES:
                assert first(task, model) == second(task, model)
        # Latency stays inside the jitter band around the catalog base.
        base = {s.name: s.latency_ms for s in bench.DIVERSE_CATALOG}
        for task in range(14):
            for model in MODEL_NAMES:
                drawn = first(task, model).latency_ms
                assert 0.6 * base[model] <= drawn <= 1.4 * base[model]

    def test_correlated_outage_hits_one_provider_in_diverse_all_in_same(self) -> None:
        diverse = bench.make_outcome_schedule(917, bench.catalog_for("diverse"))
        same = bench.make_outcome_schedule(917, bench.catalog_for("same"))
        # Task 0 is an outage task; its provider index is 0 ("alpha").
        assert diverse(0, QUICK).transient_failure
        assert not diverse(0, BALANCED).transient_failure
        assert not diverse(0, STRONG).transient_failure
        # Collapsed providers: the same outage now correlates every candidate.
        assert all(same(0, m).transient_failure for m in MODEL_NAMES)
        # Non-outage tasks are unaffected by correlation.
        assert not any(diverse(1, m).transient_failure for m in MODEL_NAMES)

    def test_scores_and_verifier_noise_stay_bounded(self) -> None:
        schedule = bench.make_outcome_schedule(917, bench.DIVERSE_CATALOG)
        for task in range(30):
            for model in MODEL_NAMES:
                outcome = schedule(task, model)
                assert 0.0 <= outcome.true_score <= 1.0
                assert 0.0 <= outcome.noisy_score <= 1.0
                if outcome.transient_failure:
                    assert not outcome.acceptable


class TestSerialCascade:
    async def test_stops_at_first_acceptable_candidate(self) -> None:
        outcome, records, counts = await _drive(
            bench.run_cascade,
            {(0, QUICK): _outcome(latency_ms=900.0, true_score=0.7, noisy_score=0.7)},
        )
        assert outcome.success
        assert outcome.latency_ms == 900.0
        assert outcome.delivered_score == 0.7
        assert len(records) == 1
        assert counts["completed"] == 1

    async def test_escalates_through_the_chain_on_unacceptable_answers(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, acceptable=False, true_score=0.2),
            (0, BALANCED): _outcome(latency_ms=2400.0, acceptable=False, true_score=0.3),
            (0, STRONG): _outcome(latency_ms=5200.0, true_score=0.95, noisy_score=0.95),
        }
        outcome, records, counts = await _drive(bench.run_cascade, table)
        assert outcome.success
        assert outcome.latency_ms == pytest.approx(900.0 + 2400.0 + 5200.0)
        assert outcome.delivered_score == 0.95
        assert [r.model for r in records] == MODEL_NAMES
        assert counts["completed"] == 3

    async def test_nobody_acceptable_is_an_honest_failure(self) -> None:
        table = {
            (0, m): _outcome(latency_ms=float(i * 1000 + 500), acceptable=False, true_score=0.1)
            for i, m in enumerate(MODEL_NAMES)
        }
        outcome, records, _ = await _drive(bench.run_cascade, table)
        assert not outcome.success
        assert outcome.delivered_score == 0.0
        assert outcome.winner_effect_key is None
        assert outcome.latency_ms == pytest.approx(500.0 + 1500.0 + 2500.0)
        # Degenerate path: every call was paid for and none delivered.
        assert all(r.billed_output == float(r.output_units) for r in records)

    async def test_transient_failure_bills_input_only(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, transient_failure=True, acceptable=False),
            (0, BALANCED): _outcome(latency_ms=2400.0, true_score=0.85),
        }
        outcome, records, counts = await _drive(bench.run_cascade, table)
        assert outcome.success
        failed = next(r for r in records if r.model == QUICK)
        assert failed.state == "failed"
        assert failed.billed_input == failed.input_units
        assert failed.billed_output == 0.0
        # A 503 is a generic provider exception: UNKNOWN, not COMPLETED.
        assert counts["unknown"] == 1
        assert counts["completed"] == 1


class TestParallelEarlyStop:
    async def test_delivers_first_acceptable_and_cancels_the_rest(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, true_score=0.7, noisy_score=0.7),
            (0, BALANCED): _outcome(latency_ms=2400.0, acceptable=False, true_score=0.3),
            (0, STRONG): _outcome(latency_ms=5200.0, true_score=0.95, noisy_score=0.95),
        }
        outcome, records, counts = await _drive(bench.run_early_stop, table)
        assert outcome.success
        assert outcome.delivered_score == 0.7  # quick-8b won on latency
        assert outcome.latency_ms == 900.0
        # Three physical calls, three Invocations: duplicates stay visible.
        assert len(records) == counts["recorded"] == 3
        # The losers were cancelled mid-flight: UNKNOWN Invocations, partial
        # output billed up to the winner's completion time.
        assert counts["completed"] == 1
        assert counts["unknown"] == 2
        loser = next(r for r in records if r.model == BALANCED)
        assert loser.state == "in_flight"
        assert loser.billed_input == loser.input_units
        assert 0.0 < loser.billed_output < float(loser.output_units)
        assert loser.billed_output == pytest.approx(
            loser.output_units * outcome.latency_ms / loser.latency_ms
        )

    async def test_waits_behind_fast_unacceptable_candidates(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, acceptable=False, true_score=0.2),
            (0, BALANCED): _outcome(latency_ms=2400.0, acceptable=False, true_score=0.3),
            (0, STRONG): _outcome(latency_ms=5200.0, true_score=0.95, noisy_score=0.95),
        }
        outcome, records, counts = await _drive(bench.run_early_stop, table)
        assert outcome.success
        assert outcome.delivered_score == 0.95
        assert outcome.latency_ms == 5200.0
        # Nothing was cancelled: the fast candidates finished unacceptable.
        assert counts["completed"] == 3
        assert all(r.state != "in_flight" for r in records)

    async def test_nobody_acceptable_waits_for_everything_and_fails(self) -> None:
        table = {
            (0, m): _outcome(latency_ms=float((i + 1) * 1000), acceptable=False, true_score=0.1)
            for i, m in enumerate(MODEL_NAMES)
        }
        outcome, _records, counts = await _drive(bench.run_early_stop, table)
        assert not outcome.success
        assert outcome.latency_ms == 3000.0  # waited for the slowest
        assert counts["completed"] == 3


class TestParallelVerifier:
    async def test_selects_noisy_best_and_counts_selection_error(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, true_score=0.9, noisy_score=0.7),
            (0, BALANCED): _outcome(latency_ms=2400.0, acceptable=False, true_score=0.3),
            (0, STRONG): _outcome(latency_ms=5200.0, true_score=0.8, noisy_score=0.95),
        }
        outcome, _records, _ = await _drive(bench.run_verifier, table)
        assert outcome.success
        # The verifier picked strong-405b on its noisy 0.95 and delivered the
        # worse answer: a counted verifier-selection error.
        assert outcome.delivered_score == 0.8
        assert outcome.verifier_error
        assert outcome.latency_ms == 5200.0

    async def test_selects_best_when_noise_is_not_adversarial(self) -> None:
        table = {
            (0, QUICK): _outcome(latency_ms=900.0, true_score=0.7, noisy_score=0.72),
            (0, BALANCED): _outcome(latency_ms=2400.0, acceptable=False, true_score=0.3),
            (0, STRONG): _outcome(latency_ms=5200.0, true_score=0.95, noisy_score=0.94),
        }
        outcome, _records, counts = await _drive(bench.run_verifier, table)
        assert outcome.success
        assert outcome.delivered_score == 0.95
        assert not outcome.verifier_error
        assert counts["completed"] == 3

    async def test_nobody_acceptable_fails_without_selection_error(self) -> None:
        table = {
            (0, m): _outcome(latency_ms=1000.0, acceptable=False, true_score=0.1)
            for m in MODEL_NAMES
        }
        outcome, _records, _ = await _drive(bench.run_verifier, table)
        assert not outcome.success
        assert not outcome.verifier_error
        assert outcome.winner_effect_key is None


class TestLedgerHonesty:
    async def test_every_physical_call_is_exactly_one_invocation(self) -> None:
        summary = await bench.run_strategy(
            "parallel-early-stop", "diverse", 2, seed=917, scale=SCALE
        )
        assert summary.physical_calls == 6
        assert summary.invocations_recorded == 6
        assert summary.invocations_completed + summary.invocations_unknown == 6

    async def test_refuses_a_physical_call_without_an_invocation(self) -> None:
        class _EmptyStore:
            async def list_effect(self, **_kw: Any) -> list[Any]:
                return []

        effects = type("_Effects", (), {"invocation_store": _EmptyStore()})()
        record = bench.PhysicalCall(
            task=0,
            model=QUICK,
            provider="alpha",
            effect_key="spec:lbl:0:quick-8b",
            latency_ms=1.0,
            acceptable=True,
            transient_failure=False,
            true_score=0.8,
            noisy_score=0.8,
            input_units=10,
            output_units=5,
        )
        with pytest.raises(RuntimeError, match="recorded 0 Invocations"):
            await bench.count_invocations(effects, {QUICK: bench._binding(QUICK)}, [record], "lbl")

    async def test_counts_a_third_status_as_other(self) -> None:
        from types import SimpleNamespace

        class _RunningStore:
            async def list_effect(self, **_kw: Any) -> list[Any]:
                return [SimpleNamespace(status=bench.InvocationStatus.RUNNING)]

        effects = type("_Effects", (), {"invocation_store": _RunningStore()})()
        record = bench.PhysicalCall(
            task=0,
            model=QUICK,
            provider="alpha",
            effect_key="spec:lbl:0:quick-8b",
            latency_ms=1.0,
            acceptable=True,
            transient_failure=False,
            true_score=0.8,
            noisy_score=0.8,
            input_units=10,
            output_units=5,
        )
        counts = await bench.count_invocations(
            effects, {QUICK: bench._binding(QUICK)}, [record], "lbl"
        )
        assert counts == {"completed": 0, "unknown": 0, "other": 1, "recorded": 1}

    async def test_refuses_a_merged_duplicate_invocation(self) -> None:
        class _DupStore:
            async def list_effect(self, **_kw: Any) -> list[Any]:
                return [object(), object()]

        effects = type("_Effects", (), {"invocation_store": _DupStore()})()
        record = bench.PhysicalCall(
            task=0,
            model=QUICK,
            provider="alpha",
            effect_key="spec:lbl:0:quick-8b",
            latency_ms=1.0,
            acceptable=True,
            transient_failure=False,
            true_score=0.8,
            noisy_score=0.8,
            input_units=10,
            output_units=5,
        )
        with pytest.raises(RuntimeError, match="recorded 2 Invocations"):
            await bench.count_invocations(effects, {QUICK: bench._binding(QUICK)}, [record], "lbl")

    async def test_completed_invocation_usage_matches_the_simulated_body(self) -> None:
        table = {(0, QUICK): _outcome(latency_ms=900.0, true_score=0.7)}
        specs = bench.DIVERSE_CATALOG
        registry = bench.build_registry(specs)
        outcome_of = _schedule(table)
        gateway = bench.SimulatedGateway(specs, outcome_of, label="usage", scale=SCALE)
        bench.set_test_transport(gateway.transport())
        try:
            effects = bench._effects()
            egress = bench.ModelChatEgress(
                effects,
                registry=registry,
                router=bench.CostAwareRouter(registry),
                endpoint=bench.ENDPOINT,
            )
            bindings = {s.name: bench._binding(s.name) for s in specs}
            await bench.run_cascade(egress, bindings, [QUICK], outcome_of, "usage", 0)
            history = await effects.invocation_store.list_effect(
                run_id="usage",
                node_run_id="t0",
                binding_id=bindings[QUICK].binding_id,
                effect_key=bench.effect_key("usage", 0, QUICK),
            )
        finally:
            bench.set_test_transport(None)
        assert len(history) == 1
        usage = history[0].usage
        assert usage is not None
        assert usage.input_units == 900
        assert usage.output_units == 350
        # 900 in @ 0.15c/1k + 350 out @ 0.60c/1k
        assert usage.cost_cents == pytest.approx(0.135 + 0.21)


class TestEndToEnd:
    async def test_runs_are_byte_identical_for_a_fixed_seed(self) -> None:
        first = asdict(
            await bench.run_strategy("parallel-early-stop", "diverse", 4, seed=917, scale=SCALE)
        )
        second = asdict(
            await bench.run_strategy("parallel-early-stop", "diverse", 4, seed=917, scale=SCALE)
        )
        assert first == second

    async def test_unknown_strategy_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy"):
            await bench.run_strategy("telepathy", "diverse", 1, seed=1, scale=SCALE)

    def test_percentile_edges(self) -> None:
        assert bench._percentile([], 50) == 0.0
        assert bench._percentile([7.0], 50) == 7.0
        assert bench._percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0

    def test_settle_billing_without_a_winner_bills_everything(self) -> None:
        records = [
            bench.PhysicalCall(
                task=0,
                model=QUICK,
                provider="alpha",
                effect_key="a",
                latency_ms=10.0,
                acceptable=False,
                transient_failure=False,
                true_score=0.1,
                noisy_score=0.1,
                input_units=100,
                output_units=50,
                state="completed",
            ),
            bench.PhysicalCall(
                task=0,
                model=BALANCED,
                provider="beta",
                effect_key="b",
                latency_ms=10.0,
                acceptable=False,
                transient_failure=True,
                true_score=0.1,
                noisy_score=0.1,
                input_units=100,
                output_units=50,
                state="failed",
            ),
        ]
        outcome = bench.TaskOutcome(False, 20.0, 0.0, False, None)
        bench._settle_billing(records, outcome)
        assert records[0].billed_input == 100.0
        assert records[0].billed_output == 50.0
        assert records[1].billed_input == 100.0
        assert records[1].billed_output == 0.0


class TestMainPayload:
    def test_payload_has_stable_shape_and_rows(self, tmp_path: Path) -> None:
        target = tmp_path / "baseline.json"
        code = asyncio.run(
            bench.main(["--tasks", "2", "--scale", str(SCALE), "--output", str(target)])
        )
        assert code == 0
        payload = json.loads(target.read_text())
        assert payload["benchmark"] == "speculative-parallel-model-calls"
        assert payload["issue"] == "917"
        assert payload["epic"] == "900"
        assert payload["tasks"] == 2
        assert payload["seed"] == bench.DEFAULT_SEED
        assert len(payload["catalog"]) == 3
        assert len(payload["results"]) == 8  # 2 topologies x 4 strategies
        assert {(r["topology"], r["strategy"]) for r in payload["results"]} == {
            (topology, strategy)
            for topology in ("diverse", "same")
            for strategy in bench.STRATEGY_ORDER
        }
        for row in payload["results"]:
            assert row["physical_calls"] == row["invocations_recorded"]
            assert row["tasks"] == 2
            assert set(row) >= {
                "p50_ms",
                "p95_ms",
                "success_rate",
                "mean_delivered_score",
                "cost_cents",
                "wasted_units",
                "cancelled_units",
                "wasted_cost_cents",
                "outage_success_rate",
                "verifier_error_rate",
                "chain",
            }

    def test_main_without_output_prints_and_returns_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = asyncio.run(bench.main(["--tasks", "1", "--scale", str(SCALE)]))
        assert code == 0
        captured = capsys.readouterr()
        assert captured.out.count("diverse/") == 4
        assert captured.out.count("same/") == 4
        assert "wrote" not in captured.out

    def test_main_rejects_zero_tasks_and_zero_scale(self) -> None:
        with pytest.raises(SystemExit):
            asyncio.run(bench.main(["--tasks", "0"]))
        with pytest.raises(SystemExit):
            asyncio.run(bench.main(["--tasks", "1", "--scale", "0"]))
