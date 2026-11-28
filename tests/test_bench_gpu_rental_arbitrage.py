"""Tests for `scripts/bench_gpu_rental_arbitrage.py` (issue #2121, epic #905 M8-F).

The root suite is the coverage producer for `scripts/`, so the bench's lines
are scored by the diff-coverage gate. Beyond coverage, these tests pin the
properties that make the arbitrage numbers trustworthy and the trust boundary
real:

- schema contract (AC1): versioned offers; missing/stale/false offers
  (non-finite price, negative price, wrong schema version, expired TTL,
  zero capacity, unknown GPU, unapproved host, sub-floor reliability) are
  rejected by a stable reason and never ranked;
- capability contract (AC1): unknown (gpu, quant, stack/version, context,
  concurrency, task) cells are INELIGIBLE, never guessed, and recorded
  INCOMPATIBLE cells are equally ineligible; the int4 hardware rule uses the
  published GPU facts;
- expected-cost ranking (AC2/AC3): advertised leads are risk-adjusted by
  modeled availability (the $0.02/h lead loses to every verified offer once
  priced at its availability), quality floor constrains the quality-adjusted
  route, fixed-gpu fails closed on workloads its SKU cannot serve, and
  cheapest-listed selects the trap lead;
- failure injection (AC4): preemption checkpoints and requeues under the
  same idempotency key with exactly one completion per key and visible redo
  spend, stale offers are re-rejected at execution time, drained hosts
  fail over through the SAME selection path, OOM/model-mismatch never rent,
  invalid prices never enter ranking, the billing cap refuses further spend;
- determinism: byte-identical reports for identical arguments, stable under
  repeated module reloads;
- trust boundary (AC6/design item 7): the harness performs no network I/O —
  asserted structurally by AST over the script's own imports and calls, so
  the proof cannot rot the way a reviewed-once claim would;
- the disposition (AC7) says no-go, keeps #934 at WATCH, and explains what
  real-hardware evidence would have to exist before INCUBATE.

Everything runs offline at deliberately small scale (no network, no database)
so the suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_gpu_rental_arbitrage.py"

spec = importlib.util.spec_from_file_location("bench_gpu_rental_arbitrage", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)

NOW = 1_000_000.0


def _walk_numbers(value: object) -> Iterator[float]:
    """Yield every number in a JSON-shaped structure."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_numbers(child)


def _offer(**overrides: object) -> bench.MarketplaceOffer:
    """A schema-valid base offer with per-test overrides."""
    base: dict[str, object] = {
        "schema_version": bench.OFFER_SCHEMA_VERSION,
        "offer_id": "t-3090",
        "host": "vast",
        "gpu_sku": "RTX_3090_24GB",
        "region": "us-central",
        "price_usd_per_hour": 0.21,
        "cpu_usd_per_hour": 0.02,
        "storage_usd_per_month": 5.0,
        "egress_usd_per_gb": 0.02,
        "reliability": 0.97,
        "min_duration_hours": 1.0,
        "preemptible": True,
        "start_time_seconds": 120.0,
        "capacity_gpus": 8,
        "price_basis": "verified",
        "captured_at": NOW,
        "ttl_seconds": 300.0,
    }
    base.update(overrides)
    return bench.MarketplaceOffer(**base)  # type: ignore[arg-type]


def _workload(**overrides: object) -> bench.WorkloadClass:
    base: dict[str, object] = {
        "name": "chat",
        "model_class": "7b-int4",
        "context_bucket": "4k",
        "reasoning": False,
        "tasks_per_class": 6,
    }
    base.update(overrides)
    return bench.WorkloadClass(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# AC1 — the versioned offer schema and its freshness/eligibility rules.
# --------------------------------------------------------------------------


class TestOfferSchema:
    def test_schema_version_is_pinned(self) -> None:
        assert bench.OFFER_SCHEMA_VERSION == "1"

    def test_valid_offer_is_eligible(self) -> None:
        decision = bench.evaluate_offer(_offer(), NOW)
        assert decision.eligible
        assert decision.reason == ""

    def test_wrong_schema_version_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(schema_version="0"), NOW)
        assert not decision.eligible
        assert decision.reason == "schema_version"

    @pytest.mark.parametrize("price", [-0.10, 0.0, math.nan, math.inf])
    def test_false_prices_rejected(self, price: float) -> None:
        decision = bench.evaluate_offer(_offer(price_usd_per_hour=price), NOW)
        assert not decision.eligible
        assert decision.reason == "invalid_price"

    def test_negative_cpu_rate_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(cpu_usd_per_hour=-0.01), NOW)
        assert not decision.eligible
        assert decision.reason == "invalid_price"

    def test_expired_ttl_rejected_as_stale(self) -> None:
        stale = _offer(captured_at=NOW - 600.0, ttl_seconds=60.0)
        assert not bench.evaluate_offer(stale, NOW).eligible
        assert bench.evaluate_offer(stale, NOW).reason == "stale"

    def test_ttl_boundary_is_exclusive(self) -> None:
        """An offer is fresh strictly before captured_at + ttl."""
        edge = _offer(captured_at=NOW - 300.0, ttl_seconds=300.0)
        assert not bench.evaluate_offer(edge, NOW).eligible  # exactly at expiry
        assert bench.evaluate_offer(edge, NOW - 1.0).eligible  # one second before

    def test_unapproved_host_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(host="cheapcloud"), NOW)
        assert not decision.eligible
        assert decision.reason == "host_unapproved"

    def test_subfloor_reliability_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(reliability=0.55), NOW)
        assert not decision.eligible
        assert decision.reason == "unreliable"

    def test_zero_capacity_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(capacity_gpus=0), NOW)
        assert not decision.eligible
        assert decision.reason == "no_capacity"

    def test_unknown_gpu_rejected(self) -> None:
        decision = bench.evaluate_offer(_offer(gpu_sku="RTX_XYZ_99GB"), NOW)
        assert not decision.eligible
        assert decision.reason == "unknown_gpu"

    def test_rejection_order_is_deterministic(self) -> None:
        """The first failing rule in contract order names the rejection."""
        mess = _offer(
            schema_version="0",
            price_usd_per_hour=-1.0,
            captured_at=0.0,
            host="cheapcloud",
            reliability=0.1,
            capacity_gpus=0,
            gpu_sku="NOPE",
        )
        decision = bench.evaluate_offer(mess, NOW)
        assert decision.reason == "schema_version"

    def test_feed_rejects_every_broken_fixture(self) -> None:
        """The feed's false/stale/trust fixtures are all rejected, by name."""
        decisions = [bench.evaluate_offer(o, NOW) for o in bench.offer_feed(NOW)]
        rejected = {d.offer_id: d.reason for d in decisions if not d.eligible}
        assert rejected["vast-3090-stale"] == "stale"
        assert rejected["bad-3090-nan"] == "invalid_price"
        assert rejected["bad-3090-neg"] == "invalid_price"
        assert rejected["bad-4090-oldschema"] == "schema_version"
        assert rejected["hostify-3060-018"] == "host_unapproved"
        assert rejected["lead-a40-006"] == "host_unapproved"
        assert rejected["vast-lowrel-4090"] == "unreliable"
        assert rejected["vast-3090-cap0"] == "no_capacity"
        # The approved-host 3060 lead passes the SCHEMA gate — it is ranked
        # by expected cost and loses there, which is the point of AC1+AC2.
        assert "lead-3060-002" not in rejected


class TestCapabilityRegistry:
    def test_registry_is_sparse_by_design(self) -> None:
        """Most (gpu, quant, stack) cells are absent: unknown is the norm."""
        registry = bench.capability_registry()
        assert len(registry) < len(bench.GPU_SPECS) * 6  # deliberately sparse
        assert all(r.provenance == "synthetic-fixture" for r in registry.values())
        assert not any("hardware" in r.provenance for r in registry.values())

    def test_unknown_cell_is_ineligible_not_guessed(self) -> None:
        """The 3060 has NO registry cell at all: ineligible for everything."""
        offer = _offer(gpu_sku="RTX_3060_12GB")
        eligible, reason, record = bench.workload_eligible(offer, _workload(), NOW)
        assert not eligible
        assert reason == "model_mismatch"
        assert record is None

    def test_recorded_incompatible_cell_is_ineligible(self) -> None:
        """3090 + fp16 at 32k summarization is recorded INCOMPATIBLE."""
        key = bench.CapabilityKey(
            gpu_sku="RTX_3090_24GB",
            quantization="fp16",
            serving_stack="vllm",
            stack_version="0.6.4",
            context_bucket="32k",
            concurrency=1,
            task_class="summarization",
        )
        record = bench.capability_registry()[key]
        assert not record.compatible

    def test_int4_hardware_rule_uses_published_facts(self) -> None:
        """P40 lacks the int4 weight-only path: ineligible before any guess."""
        offer = _offer(gpu_sku="TESLA_P40_24GB")
        eligible, reason, _ = bench.workload_eligible(
            offer, _workload(name="chat", context_bucket="4k"), NOW
        )
        assert not eligible
        assert reason == "model_mismatch"

    def test_vram_mismatch_is_oom_after_a_compatible_cell(self) -> None:
        """A 70B model on a verified 24GB cell: OOM, not mismatch."""
        offer = _offer(gpu_sku="RTX_3090_24GB")
        heavy = _workload(name="summarization", model_class="70b-int4")
        eligible, reason, record = bench.workload_eligible(offer, heavy, NOW)
        assert not eligible
        assert reason == "oom"
        assert record is not None and record.compatible

    def test_gpu_specs_cover_the_research_matrix(self) -> None:
        """The eight matrix SKUs exist with published-fact fields."""
        for sku in (
            "RTX_3060_12GB",
            "TESLA_P40_24GB",
            "TESLA_V100_32GB",
            "RTX_3090_24GB",
            "A40_48GB",
            "RTX_4090_24GB",
            "RTX_5090_32GB",
            "B200_192GB",
        ):
            spec = bench.GPU_SPECS[sku]
            assert spec.vram_gb > 0 and spec.watts > 0


# --------------------------------------------------------------------------
# AC2/AC3 — expected accepted-task cost and the four routes.
# --------------------------------------------------------------------------


class TestExpectedCost:
    def test_leads_are_risk_adjusted(self) -> None:
        """The $0.02/h lead costs more per GPU-hour than a verified 3090."""
        lead = next(o for o in bench.offer_feed(NOW) if o.offer_id == "lead-3060-002")
        verified = next(o for o in bench.offer_feed(NOW) if o.offer_id == "vast-3090-021")
        assert lead.price_usd_per_hour < verified.price_usd_per_hour / 10
        assert bench.risk_adjusted_hourly_cost(lead) > bench.risk_adjusted_hourly_cost(verified)
        assert lead.availability_probability() == bench.LEAD_AVAILABILITY

    def test_risk_adjustment_is_arithmetic_not_a_label(self) -> None:
        """Lead availability divides the full hourly rate, it does not merely
        annotate it: the same division the ranking uses."""
        offer = _offer(price_basis="advertised", price_usd_per_hour=0.50)
        assert offer.availability_probability() == bench.LEAD_AVAILABILITY
        hourly = offer.hourly_cost()
        hourly += offer.storage_usd_per_month / (30.0 * bench.STORAGE_AMORTIZATION_HOURS)
        hourly += offer.egress_usd_per_gb * 0.5
        assert bench.risk_adjusted_hourly_cost(offer) == pytest.approx(
            hourly / bench.LEAD_AVAILABILITY, rel=1e-9
        )

    def test_expected_cost_scales_with_acceptance(self) -> None:
        """Priced as attempts-per-accepted-task: 1/acceptance, exactly."""
        offer = _offer()
        workload = _workload()
        record = bench.capability_for(offer, workload)
        assert record is not None
        base = bench.expected_accepted_task_cost(offer, record, workload)
        worse = bench.CapabilityRecord(True, record.decode_tokens_per_s, 0.5, record.warmup_seconds)
        worse_cost = bench.expected_accepted_task_cost(offer, worse, workload)
        # Only the acceptance term changed (reliability is the offer's, and
        # the redo multiplier cancels): the ratio is exactly acceptance ratio.
        assert worse_cost == pytest.approx(base * record.acceptance / 0.5, rel=1e-12)

    def test_preemption_redo_multiplier_only_on_preemptible(self) -> None:
        fixed = _offer(preemptible=False)
        loose = _offer(preemptible=True)
        assert bench.redo_multiplier(fixed) == 1.0
        assert bench.redo_multiplier(loose) == pytest.approx(1.0 + bench.PREEMPTION_RATE * 0.5)

    def test_zero_acceptance_is_never_viable(self) -> None:
        dead = bench.CapabilityRecord(True, 50.0, 0.0, 0.0)
        cost = bench.expected_accepted_task_cost(_offer(), dead, _workload())
        assert cost == math.inf
        assert bench.dollars_per_mtok_accepted(_offer(), dead, _workload()) == math.inf

    def test_per_mtok_diagnostic_is_cost_over_tokens(self) -> None:
        offer = _offer()
        workload = _workload()
        record = bench.capability_for(offer, workload)
        assert record is not None
        cost = bench.expected_accepted_task_cost(offer, record, workload)
        tokens = bench.output_tokens_per_task(workload)
        mtok = bench.dollars_per_mtok_accepted(offer, record, workload)
        assert mtok == pytest.approx(cost / (tokens / 1e6), rel=1e-6)


class TestRoutes:
    def test_cheapest_listed_picks_the_trap_lead(self) -> None:
        """The naive route sorts by sticker price and finds the $0.02 lead."""
        pick, reason = bench.select_cheapest_listed(bench.offer_feed(NOW))
        assert reason == ""
        assert pick is not None
        assert pick.offer_id == "lead-3060-002"
        assert pick.price_basis == "advertised"

    def test_cheapest_eligible_never_picks_an_ineligible_offer(self) -> None:
        offers = bench.offer_feed(NOW)
        for workload in bench.WORKLOAD_CLASSES:
            pick, reason, cost = bench.select_cheapest_eligible(offers, workload, NOW)
            assert reason == "", workload.name
            assert pick is not None
            eligible, _, _ = bench.workload_eligible(pick, workload, NOW)
            assert eligible
            assert cost < math.inf
            assert pick.price_basis == "verified"

    def test_lead_with_capability_cell_loses_on_expected_cost(self) -> None:
        """The advertised 4090 lead is capability-eligible yet never wins.

        This pins the risk-adjustment mechanism itself: the lead loses NOT on
        eligibility but on expected accepted-task cost — the issue's rule
        that advertised prices are leads, not availability guarantees.
        """
        offers = bench.offer_feed(NOW)
        workload = bench.WORKLOAD_CLASSES[0]
        lead = next(o for o in offers if o.offer_id == "lead-4090-005")
        eligible, _, record = bench.workload_eligible(lead, workload, NOW)
        assert eligible and record is not None  # it IS in the feasible set
        winner, _, winner_cost = bench.select_cheapest_eligible(offers, workload, NOW)
        assert winner is not None and winner.offer_id != lead.offer_id
        lead_cost = bench.expected_accepted_task_cost(lead, record, workload)
        assert lead_cost > winner_cost

    def test_quality_floor_constrains_the_quality_route(self) -> None:
        offers = bench.offer_feed(NOW)
        for workload in bench.WORKLOAD_CLASSES:
            pick, reason, _ = bench.select_quality_adjusted(offers, workload, NOW)
            assert reason == "", workload.name
            assert pick is not None
            record = bench.capability_for(pick, workload)
            assert record is not None
            assert record.acceptance >= bench.QUALITY_FLOOR

    def test_fixed_gpu_fails_closed_on_unserviceable_classes(self) -> None:
        """The pinned 3090 has no 70B-class cell: heavy routes fail closed."""
        offers = bench.offer_feed(NOW)
        for workload in bench.WORKLOAD_CLASSES:
            pick, reason = bench.select_fixed_gpu(offers, workload, NOW, "RTX_3090_24GB")
            if workload.model_class == "70b-int4":
                assert pick is None
                assert reason == "model_mismatch"
            else:
                assert pick is not None, workload.name

    def test_fixed_gpu_falls_through_stale_listings(self) -> None:
        """The stale 3090 listing is cheaper; the route skips it anyway."""
        offers = bench.offer_feed(NOW)
        pick, reason = bench.select_fixed_gpu(
            offers, bench.WORKLOAD_CLASSES[0], NOW, "RTX_3090_24GB"
        )
        assert reason == ""
        assert pick is not None
        assert pick.offer_id == "vast-3090-021"

    def test_fixed_gpu_without_listings(self) -> None:
        pick, reason = bench.select_fixed_gpu([], _workload(), NOW, "RTX_5090_32GB")
        assert pick is None
        assert reason == "no_offer_for_sku"

    def test_no_eligible_offer_when_feed_is_empty(self) -> None:
        pick, reason, cost = bench.select_cheapest_eligible([], _workload(), NOW)
        assert pick is None
        assert reason == "no_eligible_offer"
        assert cost == math.inf

    def test_cheapest_listed_with_no_valid_offer(self) -> None:
        """A feed whose every listing fails schema/price fails closed."""
        garbage = [
            _offer(offer_id="a", schema_version="0"),
            _offer(offer_id="b", price_usd_per_hour=math.nan),
        ]
        pick, reason = bench.select_cheapest_listed(garbage)
        assert pick is None
        assert reason == "no_valid_offer"

    def test_quality_route_reports_floor_miss(self) -> None:
        pick, reason, cost = bench.select_quality_adjusted([], _workload(), NOW)
        assert pick is None
        assert reason == "no_offer_above_quality_floor"
        assert cost == math.inf

    def test_route_comparison_shape(self) -> None:
        comparison = bench.route_comparison("gpu-arb-v1", 6, NOW)
        assert comparison["data_class"] == "simulation"
        routes = comparison["routes"]
        assert set(routes) == {w.name for w in bench.WORKLOAD_CLASSES}
        for row in routes.values():
            assert set(row) == {
                "fixed-gpu",
                "cheapest-listed",
                "cheapest-eligible",
                "quality-adjusted",
            }
            for route in row.values():
                assert route["reason"] is not None

    def test_report_labels_every_data_class_simulation(self) -> None:
        report = bench.run_benchmark(tasks_per_class=2)
        assert report["routes"]["data_class"] == "simulation"
        assert report["offer_feed"]["data_class"] == "simulation"
        assert report["annual_sensitivity_usd"]["22"]["data_class"] == "simulation"
        assert report["capability_registry"]["hardware_measured_cells"] == 0
        assert "simulated" in report["provenance"]["observed_data"]


# --------------------------------------------------------------------------
# AC4 — failure injection with idempotent, capped execution.
# --------------------------------------------------------------------------


class TestReplayLedger:
    def test_completed_key_never_executes_twice(self) -> None:
        ledger = bench.ReplayLedger()
        calls: list[str] = []

        def body() -> tuple[float, bool]:
            calls.append("run")
            return 0.01, True

        billed, done = ledger.attempt("t1", body)
        assert billed == 0.01 and done
        billed, done = ledger.attempt("t1", body)  # duplicate submission
        assert billed == 0.0 and done
        assert calls == ["run"]  # executed ONCE
        assert ledger.billed_usd == 0.01
        assert any(e.startswith("idempotent-skip") for e in ledger.events)

    def test_checkpoint_does_not_complete_the_key(self) -> None:
        """A preempted attempt bills its tail and requeues; the key completes
        only on the resuming attempt."""
        ledger = bench.ReplayLedger()
        billed, done = ledger.attempt("t1", lambda: (0.005, False))
        assert billed == 0.005
        assert ledger.billed_usd == pytest.approx(0.005)
        assert not done
        assert not ledger.is_complete("t1")
        assert any(e.startswith("checkpoint-requeue") for e in ledger.events)
        billed2, done2 = ledger.attempt("t1", lambda: (0.01, True))
        assert done2
        assert ledger.is_complete("t1")
        assert ledger.completed["t1"] == 1
        assert ledger.billed_usd == pytest.approx(billed + billed2)


class TestFailureInjection:
    def test_all_modes_report_a_payload(self) -> None:
        modes = [
            "benign",
            "preemption",
            "stale_offer",
            "host_unavailable",
            "oom",
            "model_mismatch",
            "invalid_price",
            "billing_cap",
        ]
        for mode in modes:
            payload = bench.run_replay(mode, tasks_per_class=3)
            assert payload["mode"] == mode

    def test_preemption_dups_no_work_and_bills_redo(self) -> None:
        benign = bench.run_replay("benign", tasks_per_class=20)
        preempt = bench.run_replay("preemption", tasks_per_class=20)
        # Same accepted count: every task still completes exactly once.
        assert preempt["accepted"] == benign["accepted"]
        assert preempt["distinct_keys_completed"] == benign["distinct_keys_completed"]
        assert preempt["distinct_keys_completed"] == benign["accepted"]
        # With preemptions drawn, redo spend is visible, not silently dropped.
        assert preempt["billed_usd"] > benign["billed_usd"]
        assert any(e.startswith("checkpoint-requeue") for e in preempt.get("events", []))

    def test_billing_cap_fails_closed(self) -> None:
        payload = bench.run_replay("billing_cap", tasks_per_class=20)
        assert payload["accepted"] < 20
        assert payload["route_failures"] == 20 - payload["accepted"]
        assert any(e.startswith("billing-cap-refusal") for e in payload.get("events", []))
        benign = bench.run_replay("benign", tasks_per_class=20)
        assert payload["billed_usd"] <= benign["billed_usd"]

    def test_stale_offer_refuses_at_execution_time(self) -> None:
        payload = bench.run_replay("stale_offer", tasks_per_class=4)
        assert payload["accepted"] == 0
        assert payload["billed_usd"] == 0.0
        assert "stale" in str(payload["note"])

    def test_oom_never_rents(self) -> None:
        payload = bench.run_replay("oom", tasks_per_class=4)
        assert payload["accepted"] == 0
        assert payload["billed_usd"] == 0.0
        assert "oom" in str(payload["note"])

    def test_model_mismatch_is_pre_flight(self) -> None:
        payload = bench.run_replay("model_mismatch", tasks_per_class=4)
        assert payload["accepted"] == 0
        assert payload["billed_usd"] == 0.0
        assert "model_mismatch" in str(payload["note"])

    def test_invalid_price_never_enters_ranking(self) -> None:
        payload = bench.run_replay("invalid_price")
        bad = payload["rejected_at_ingestion"]
        assert sorted(bad) == ["bad-3090-nan", "bad-3090-neg"]
        assert payload["billed_usd"] == 0.0

    def test_drained_host_fails_over_through_the_same_path(self) -> None:
        payload = bench.run_replay("host_unavailable", tasks_per_class=4)
        assert payload["route_failures"] == 0
        assert "failover target" in str(payload["note"])
        assert "salad-4090-032" in str(payload["note"])
        assert "vast-4090-034" in str(payload["note"])

    def test_unknown_selection_failure_fails_closed(self) -> None:
        """An empty candidate set reports route failures, not fake success."""
        original = bench.select_cheapest_eligible
        bench.select_cheapest_eligible = lambda *a, **k: (None, "no_eligible_offer", math.inf)  # type: ignore[assignment]
        try:
            payload = bench.run_replay("benign", tasks_per_class=2)
        finally:
            bench.select_cheapest_eligible = original  # type: ignore[assignment]
        assert payload["accepted"] == 0
        assert payload["route_failures"] == 2
        assert "selection failed" in str(payload["note"])


# --------------------------------------------------------------------------
# AC5 — annual sensitivity.
# --------------------------------------------------------------------------


class TestAnnualSensitivity:
    def test_24h_costs_more_than_22h(self) -> None:
        tco22 = bench.annual_tco(22)
        tco24 = bench.annual_tco(24)
        for basis in bench.PRICE_BASES:
            r22 = tco22["strategies_usd_per_year"][basis]["always-rented"]
            r24 = tco24["strategies_usd_per_year"][basis]["always-rented"]
            assert r24 > r22
            assert r24 == pytest.approx(r22 * 24 / 22, rel=1e-6)

    def test_strategies_are_ordered_sensibly(self) -> None:
        """On-demand-heavy pays the premium only on its task share."""
        tco = bench.annual_tco(22)["strategies_usd_per_year"]["mid"]
        always = tco["always-rented"]
        ondemand = tco["heavy-model-on-demand"]
        owned = tco["owned-16gb-plus-cloud"]
        assert owned < always  # the owned GPU covers most hours
        assert ondemand > owned  # the heavy premium costs more than power

    def test_lead_basis_is_annotated_unverified(self) -> None:
        tco = bench.annual_tco(24)
        assert "IF TRUE" in tco["strategies_usd_per_year"]["lead"]["price_basis_note"]
        assert "unverified" in tco["strategies_usd_per_year"]["lead"]["price_basis_note"]

    def test_owned_power_scales_with_hours(self) -> None:
        owned22 = bench._owned_annual_usd(22)
        owned24 = bench._owned_annual_usd(24)
        assert owned24["power_usd"] > owned22["power_usd"]
        assert owned22["capex_amortized_usd"] == owned24["capex_amortized_usd"]

    def test_both_hours_in_report_by_default(self) -> None:
        report = bench.run_benchmark(tasks_per_class=2)
        assert set(report["annual_sensitivity_usd"]) == {"22", "24"}
        report22 = bench.run_benchmark(tasks_per_class=2, hours="22")
        assert set(report22["annual_sensitivity_usd"]) == {"22"}


# --------------------------------------------------------------------------
# Determinism (AC2) and CLI.
# --------------------------------------------------------------------------


class TestDeterminismAndCLI:
    def test_report_is_byte_identical_for_identical_args(self) -> None:
        a = json.dumps(bench.run_benchmark("gpu-arb-v1", 4), sort_keys=True)
        b = json.dumps(bench.run_benchmark("gpu-arb-v1", 4), sort_keys=True)
        assert a == b

    def test_seed_moves_the_report(self) -> None:
        a = json.dumps(bench.run_benchmark("seed-a", 4), sort_keys=True)
        b = json.dumps(bench.run_benchmark("seed-b", 4), sort_keys=True)
        assert a != b  # the preemption draws are seed-keyed

    def test_no_wall_clock_in_the_report(self) -> None:
        """No generated-at key and no date-shaped value ever enters the JSON."""
        report = bench.run_benchmark("gpu-arb-v1", 2)
        text = json.dumps(report)
        assert "generated_at" not in text
        date_like = re.compile(r"\d{4}-\d{2}-\d{2}T")
        assert not date_like.search(text)
        # Epoch-second reading of a real clock (post-2020) would be > 1.6e9;
        # the only time-like constants in the report are the fixed 1e6
        # evaluation instant, never a wall-clock sample.
        for value in _walk_numbers(report):
            assert value < 1.6e9

    def test_cli_writes_json_to_output(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        rc = bench.main(["--tasks-per-class", "2", "--output", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["benchmark"] == "gpu-rental-arbitrage"
        assert payload["issue"] == "2121"

    def test_cli_defaults_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = bench.main(["--tasks-per-class", "2"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["disposition"]["go_no_go"] == "no-go"

    def test_cli_rejects_unknown_hours(self) -> None:
        with pytest.raises(SystemExit):
            bench.main(["--hours", "25"])


# --------------------------------------------------------------------------
# AC6/design item 7 — the trust boundary is structural, not promised.
# --------------------------------------------------------------------------


class TestTrustBoundary:
    def test_script_imports_no_network_module(self) -> None:
        """AST over the script's own imports: the offline claim cannot rot."""
        tree = ast.parse(SCRIPT.read_text())
        banned = {
            "socket",
            "ssl",
            "urllib",
            "urllib2",
            "http",
            "httpx",
            "requests",
            "aiohttp",
            "ftplib",
            "telnetlib",
            "smtplib",
            "asyncio",
            "subprocess",
            "time",
            "datetime",
            "uuid",
            "random",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                root = node.names[0].name.split(".")[0]
                assert root not in banned, f"bench imports network/system module: {root}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in banned, f"bench imports network/system module: {root}"

    def test_script_makes_no_effect_calls(self) -> None:
        """No attribute call in the script can be a network effect call."""
        tree = ast.parse(SCRIPT.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "open_connection",
                "create_connection",
                "urlopen",
                "request",
                "post",
                "put",
                "patch",
                "delete",
                "exec",
                "run",
            }:
                pytest.fail(f"bench references effect call: {node.attr}")

    def test_disposition_is_explicit(self) -> None:
        d = bench.disposition()
        assert d["go_no_go"] == "no-go"
        assert d["issue_934_disposition"].startswith("WATCH")
        assert d["issue_934_incubate_now"] is False
        assert any("real-hardware" in str(p) for p in d["issue_934_incubate_preconditions"])

    def test_report_carries_trust_controls(self) -> None:
        report = bench.run_benchmark(tasks_per_class=2)
        controls = report["trust_controls"]
        assert "no network module" in controls["network_io"]
        assert "APPROVED_HOSTS" in controls["operator_approval"]
        assert "fails closed" in controls["unattended_deposit"]
        assert "CostAwareRouter" in controls["egress_authority"]
