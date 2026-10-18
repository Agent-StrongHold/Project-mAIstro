"""Tests for bounded frontier-model RSI campaigns (M5-B, #114).

Each acceptance criterion from the issue is pinned here:

- ceilings: a campaign must declare explicit spend/quota/time/work-scope
  bounds and refuses to start without any (ceiling-1..3);
- canonical tracking: every dispatched model call is a canonical Invocation
  in the store, usage/cost-attributed, and charged exactly once to the quota
  ledger through the canonical recorder (track-1..5);
- comparison: the frontier arm and the cheaper baseline arm run the identical
  objective pool and the report compares them on it (compare-1..4);
- reporting: verified progress, cost, attempts, regressions and intervention
  rates are recorded in a serializable artifact (report-1..3);
- mechanical stop: the campaign stops itself at budget/stop conditions —
  before attempts and inside the dispatch seam (stop-1..6).
"""

from __future__ import annotations

import asyncio
import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationStatus,
    InvocationUsage,
)
from maistro.providers.types import ModelMetadata
from maistro.quota.billing import cycle_key
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog
from maistro_rsi.campaign import (
    ArmPolicy,
    BudgetExhausted,
    BudgetState,
    CampaignCeilings,
    CampaignReport,
    ModelCallResult,
    Objective,
    ObjectivePool,
    ensure_bounded,
    ensure_unique_objectives,
    gateway_model_call,
    keyword_objective_scorer,
    run_campaign,
)

WS = "ws-campaign"
PROJ = "proj-campaign"
CYCLE = "monthly"

FRONTIER_PRICING = ModelMetadata(
    name="frontier/max",
    provider="frontier",
    cost_per_1k_input=30.0,  # cents per 1k tokens
    cost_per_1k_output=60.0,
    latency_p50_ms=900,
)
BASELINE_PRICING = ModelMetadata(
    name="free/mini",
    provider="free",
    cost_per_1k_input=0.0,
    cost_per_1k_output=0.0,
    latency_p50_ms=300,
)


def _pool(*objectives: Objective) -> ObjectivePool:
    return ObjectivePool(objectives=objectives)


def _two_objective_pool() -> ObjectivePool:
    return _pool(
        Objective(objective_id="obj-1", task="Cover alpha and beta", keywords=("alpha", "beta")),
        Objective(objective_id="obj-2", task="Cover gamma", keywords=("gamma",)),
    )


def _answered(
    content: str, *, inp: int = 10, out: int = 5, version: str = "max-2026"
) -> ModelCallResult:
    return ModelCallResult(
        content=content,
        input_tokens=inp,
        output_tokens=out,
        usage_reported=True,
        model_version=version,
    )


def _scripted_call(script: dict[str, ModelCallResult | Exception]) -> Any:
    """A ModelCall that answers each objective task with a scripted result."""

    async def call(
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ModelCallResult:
        result = script[messages[0]["content"]]
        if isinstance(result, Exception):
            raise result
        return result

    return call


def _per_model_calls(per_model: dict[str, Any]) -> Any:
    return lambda arm: per_model[arm.model]


def _pricing(arm: ArmPolicy) -> ModelMetadata | None:
    return FRONTIER_PRICING if arm.arm_id == "frontier" else BASELINE_PRICING


def _arms() -> list[ArmPolicy]:
    return [
        ArmPolicy(arm_id="frontier", model="frontier/max"),
        ArmPolicy(arm_id="baseline", model="free/mini"),
    ]


async def _run(pool: ObjectivePool, ceilings: CampaignCeilings, **kwargs: Any) -> Any:
    return await run_campaign(
        run_id=kwargs.pop("run_id", "run-c1"),
        pool=pool,
        arms=kwargs.pop("arms", _arms()),
        ceilings=ceilings,
        make_model_call=kwargs.pop(
            "make_model_call",
            _per_model_calls(
                {
                    "frontier/max": _scripted_call(
                        {
                            "Cover alpha and beta": _answered("alpha beta"),
                            "Cover gamma": _answered("gamma"),
                        }
                    ),
                    "free/mini": _scripted_call(
                        {
                            "Cover alpha and beta": _answered("alpha beta"),
                            "Cover gamma": _answered("gamma"),
                        }
                    ),
                }
            ),
        ),
        store=kwargs.pop("store", InMemoryInvocationStore()),
        usage_log=kwargs.pop("usage_log", InMemoryUsageLog()),
        quota_tracker=kwargs.pop("quota_tracker", InMemoryQuotaTracker()),
        pricing=kwargs.pop("pricing", _pricing),
        workspace_id=WS,
        project_id=PROJ,
        **kwargs,
    )


# -- ceiling-1..2: a campaign declares explicit ceilings ----------------------


class TestCampaignCeilings:
    def test_unbounded_policy_never_becomes_enforcement(self):
        """ceiling-1: an unbounded campaign refuses to start — BudgetState
        (the enforcement point) refuses it, so no run can begin unbounded."""
        CampaignCeilings()  # declarative model: constructing is harmless
        with pytest.raises(ValueError, match="at least one explicit ceiling"):
            BudgetState(CampaignCeilings())
        ensure_bounded(CampaignCeilings(max_spend_usd=1.0))  # bounded: accepted

    async def test_run_campaign_refuses_unbounded_ceilings(self):
        with pytest.raises(ValueError, match="at least one explicit ceiling"):
            await _run(_two_objective_pool(), CampaignCeilings())

    @pytest.mark.parametrize(
        "ceilings",
        [
            CampaignCeilings(max_spend_usd=1.0),
            CampaignCeilings(max_total_tokens=1000),
            CampaignCeilings(max_model_calls=5),
            CampaignCeilings(max_wall_clock_s=60.0),
            CampaignCeilings(max_objectives=2),
            CampaignCeilings(allowed_paths=("src/",)),
        ],
    )
    def test_each_single_axis_is_a_sufficient_ceiling(self, ceilings: CampaignCeilings):
        """ceiling-1: any one bounded axis makes the campaign admissible."""
        assert ceilings.model_dump() is not None

    @pytest.mark.parametrize(
        "field", ["max_spend_usd", "max_total_tokens", "max_model_calls", "max_wall_clock_s"]
    )
    def test_nonpositive_ceilings_are_refused(self, field: str):
        """ceiling-2: a ceiling of zero or less is a misconfiguration."""
        with pytest.raises(ValidationError):
            CampaignCeilings(**{field: 0})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_spend_usd", float("inf")),
            ("max_spend_usd", float("nan")),
            ("max_wall_clock_s", float("inf")),
            ("max_wall_clock_s", float("nan")),
        ],
    )
    def test_non_finite_ceilings_are_refused(self, field: str, value: float):
        """ceiling-2b: an infinite (or NaN) float ceiling is bounded in name
        only — ``inf`` is greater than zero, so it would pass a bare ``gt=0``
        and read as a bounded axis whose stop condition can never fire, with
        the campaign admitted to run the whole pool (argparse hands
        ``--max-seconds inf`` straight through as ``float('inf')``). Bounded
        means reachable, so the model refuses non-finite values outright."""
        with pytest.raises(ValidationError):
            CampaignCeilings(**{field: value})

    def test_empty_allowed_path_is_refused(self):
        with pytest.raises(ValidationError, match="at least 1 character"):
            CampaignCeilings(allowed_paths=("src/", ""))

    async def test_campaign_refuses_to_run_without_scope(self):
        """A campaign Invocation carries workspace/project scope; refusing to
        fabricate one keeps every row correlatable (#1133)."""
        with pytest.raises(ValueError, match="scope"):
            await run_campaign(
                run_id="run-x",
                pool=_two_objective_pool(),
                arms=_arms(),
                ceilings=CampaignCeilings(max_model_calls=1),
                make_model_call=lambda arm: _scripted_call({}),
                workspace_id="",
                project_id="",
            )


# -- ceiling-3: work scope ----------------------------------------------------


class TestWorkScope:
    async def test_out_of_scope_objectives_are_refused_without_dispatch(self):
        """ceiling-3: a pool entry outside allowed_paths is never dispatched,
        and the refusal is recorded (once per arm for a two-arm campaign)."""
        pool = _pool(
            Objective(
                objective_id="in-scope",
                task="Cover alpha",
                keywords=("alpha",),
                paths=("src/mod.py",),
            ),
            Objective(objective_id="out-of-scope", task="Cover gamma", paths=("tests/leak.py",)),
        )
        store = InMemoryInvocationStore()
        report = await _run(
            pool,
            CampaignCeilings(allowed_paths=("src/",)),
            store=store,
            make_model_call=_per_model_calls(
                {
                    "frontier/max": _scripted_call({"Cover alpha": _answered("alpha")}),
                    "free/mini": _scripted_call({"Cover alpha": _answered("alpha")}),
                }
            ),
        )

        assert report.scope_refusals == 2  # refused for each of the two arms
        dispatched = {inv.node_run_id for inv in store._items.values()}
        assert all("out-of-scope" not in node for node in dispatched)
        for arm in report.arms:
            assert arm.attempts == 1  # only the in-scope objective ran
            assert all(a.objective_id == "in-scope" for a in arm.attempts_log)

    async def test_scope_subset_paths_are_admitted(self):
        """ceiling-3: declared paths within the allowed prefix run normally."""
        pool = _pool(
            Objective(objective_id="scoped", task="Cover alpha", paths=("src/a.py",)),
        )
        report = await _run(
            pool,
            CampaignCeilings(allowed_paths=("src/",)),
            make_model_call=_per_model_calls(
                {
                    "frontier/max": _scripted_call({"Cover alpha": _answered("alpha")}),
                    "free/mini": _scripted_call({"Cover alpha": _answered("alpha")}),
                }
            ),
        )
        assert report.scope_refusals == 0
        assert all(arm.attempts == 1 for arm in report.arms)

    async def test_traversal_paths_are_refused(self):
        """ceiling-3: ``..`` traversal may not escape an allowed prefix; the
        declared path is normalized before containment is decided."""
        pool = _pool(
            Objective(
                objective_id="traversal",
                task="Cover alpha",
                keywords=("alpha",),
                paths=("src/../secrets.txt",),
            ),
            Objective(objective_id="escape", task="Cover gamma", paths=("../outside.py",)),
            Objective(objective_id="absolute", task="Cover delta", paths=("/etc/passwd",)),
        )
        report = await _run(pool, CampaignCeilings(allowed_paths=("src/",)))
        assert report.scope_refusals == 6  # three refused objectives, once per arm

    async def test_in_prefix_traversal_is_normalized_and_admitted(self):
        """ceiling-3: traversal that stays inside the prefix normalizes down."""
        pool = _pool(
            Objective(
                objective_id="scoped",
                task="Cover alpha",
                keywords=("alpha",),
                paths=("src/sub/../a.py",),
            ),
        )
        report = await _run(
            pool,
            CampaignCeilings(allowed_paths=("src/",)),
            make_model_call=_per_model_calls(
                {
                    "frontier/max": _scripted_call({"Cover alpha": _answered("alpha")}),
                    "free/mini": _scripted_call({"Cover alpha": _answered("alpha")}),
                }
            ),
        )
        assert report.scope_refusals == 0
        assert all(arm.attempts == 1 for arm in report.arms)

    async def test_prefix_is_not_matched_by_partial_components(self):
        """ceiling-3: containment is component-wise, so ``srcx/`` does not
        satisfy a ``src/`` ceiling the way a raw string prefix would."""
        pool = _pool(
            Objective(objective_id="lookalike", task="Cover gamma", paths=("srcx/leak.py",)),
        )
        report = await _run(pool, CampaignCeilings(allowed_paths=("src/",)))
        assert report.scope_refusals == 2


# -- stop-1..6: mechanical stops ----------------------------------------------


class TestMechanicalStops:
    @staticmethod
    def _three_objective_pool() -> ObjectivePool:
        return _pool(
            Objective(objective_id="obj-1", task="t1", keywords=("k1",)),
            Objective(objective_id="obj-2", task="t2", keywords=("k2",)),
            Objective(objective_id="obj-3", task="t3", keywords=("k3",)),
        )

    @staticmethod
    def _three_answer_calls() -> Any:
        return _per_model_calls(
            {
                "frontier/max": _scripted_call(
                    {"t1": _answered("k1"), "t2": _answered("k2"), "t3": _answered("k3")}
                ),
                "free/mini": _scripted_call(
                    {"t1": _answered("k1"), "t2": _answered("k2"), "t3": _answered("k3")}
                ),
            }
        )

    async def test_stops_at_model_call_ceiling_before_a_third_dispatch(self):
        """stop-1: the call-count ceiling mechanically refuses the third
        dispatch; the refused objective is recorded nowhere as work."""
        store = InMemoryInvocationStore()
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_model_calls=2),
            store=store,
            make_model_call=self._three_answer_calls(),
        )
        frontier = report.arms[0]
        assert frontier.stop_reason is not None
        assert frontier.stop_reason.ceiling == "max_model_calls"
        assert frontier.attempts == 2
        assert [a.objective_id for a in frontier.attempts_log] == ["obj-1", "obj-2"]
        assert len(store._items) == 4  # 2 arms x 2 dispatched calls, no more

    @staticmethod
    def _three_failing_calls() -> Any:
        """A ModelCall factory whose every dispatch raises, as a timeout/5xx
        would. The returned callable has the ``make_model_call`` shape — one
        arm in, one ``ModelCall`` out — so the arm context resolves a real
        awaitable transport instead of binding a stray coroutine object."""

        async def call(
            messages: list[dict[str, str]], *, temperature: float = 0.2, max_tokens: int = 2048
        ) -> ModelCallResult:
            raise RuntimeError("gateway 503")

        return lambda arm: call

    async def test_failed_dispatch_counts_against_call_ceiling(self):
        """A dispatch that raises (timeout, 5xx) may still have been received
        and served by the provider, so it consumes max_model_calls at
        admission: the walk stops instead of replaying one failed request
        per remaining pool entry."""
        store = InMemoryInvocationStore()
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_model_calls=1),
            store=store,
            make_model_call=self._three_failing_calls(),
        )
        frontier = report.arms[0]
        assert frontier.stop_reason is not None
        assert frontier.stop_reason.ceiling == "max_model_calls"
        assert frontier.attempts == 1  # the failed dispatch; obj-2/obj-3 never dispatched
        assert frontier.interventions == 1
        dispatched = [
            inv for inv in store._items.values() if inv.node_run_id.startswith("frontier:")
        ]
        assert len(dispatched) == 1
        # Canonical terminalization (capabilities.invocation._run_provider): a
        # generic provider exception does not prove the effect was unapplied —
        # the request may still have been served — so the row reads UNKNOWN,
        # never safe-to-retry FAILED. FAILED is reserved for EffectNotApplied.
        assert dispatched[0].status is InvocationStatus.UNKNOWN
        assert dispatched[0].error == "gateway 503"

    async def test_stops_at_spend_ceiling_mid_pool(self):
        """stop-2: measured spend stops the arm after the call that crossed it.

        Frontier pricing: 10 in @ 30c/1k + 5 out @ 60c/1k = 0.6 cents =
        $0.006 per call. A $0.005 ceiling admits the first call, sees spend
        over it, and refuses the second.
        """
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_spend_usd=0.005),
            make_model_call=self._three_answer_calls(),
        )
        frontier = report.arms[0]
        assert frontier.stop_reason is not None
        assert frontier.stop_reason.ceiling == "max_spend_usd"
        assert frontier.attempts == 1
        assert frontier.cost_usd == pytest.approx(0.006)
        # The free baseline arm walks the whole pool regardless.
        assert report.arms[1].attempts == 3

    async def test_stops_at_token_quota(self):
        """stop-3: the total-token quota (in+out) refuses new attempts."""
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_total_tokens=20),  # one call is 15 tokens
            make_model_call=self._three_answer_calls(),
        )
        for arm in report.arms:
            # After two calls (30 tokens) the quota is crossed; the third is
            # refused, so the observed overshoot is exactly one in-flight call.
            assert arm.attempts == 2
            assert arm.stop_reason is not None
            assert arm.stop_reason.ceiling == "max_total_tokens"
            assert arm.stop_reason.observed == 30
            assert arm.stop_reason.limit == 20

    async def test_stops_at_wall_clock_before_any_attempt(self):
        """stop-4: an expired clock stops the arm with zero work dispatched."""
        ticks = {"n": 0}

        def clock() -> float:
            ticks["n"] += 1
            return (ticks["n"] - 1) * 50.0

        report = await _run(
            _two_objective_pool(), CampaignCeilings(max_wall_clock_s=10.0), clock=clock
        )
        for arm in report.arms:
            assert arm.attempts == 0
            assert arm.stop_reason is not None
            assert arm.stop_reason.ceiling == "max_wall_clock_s"

    async def test_in_flight_call_is_cancelled_at_wall_clock_expiry(self):
        """stop-4b: the wall-clock ceiling bounds the in-flight request, not
        just the pre-dispatch gate — a call that hangs past its remaining
        budget (e.g. against a 60s transport timeout with a 1s ceiling) is
        cancelled at the clock; the row terminalizes UNKNOWN and the expiry
        surfaces as the designed mechanical stop, not an intervention."""

        async def hanging_call(
            messages: list[dict[str, str]],
            *,
            temperature: float = 0.2,
            max_tokens: int = 2048,
        ) -> ModelCallResult:
            await asyncio.sleep(3600)
            raise AssertionError("the wall-clock cap should have cancelled this")

        store = InMemoryInvocationStore()
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_wall_clock_s=0.2),
            store=store,
            arms=[ArmPolicy(arm_id="frontier", model="frontier/max")],
            make_model_call=lambda arm: hanging_call,
        )
        frontier = report.arms[0]
        assert frontier.objectives_attempted == 1  # admitted, then cut off
        assert frontier.attempts == 1  # the admitted in-flight dispatch counts
        assert frontier.attempts_log == ()  # cut-off lands as the stop, not a record
        assert frontier.interventions == 0
        assert frontier.stop_reason is not None
        assert frontier.stop_reason.ceiling == "max_wall_clock_s"
        assert frontier.stop_reason.observed >= 0.2
        assert frontier.stop_reason.limit == 0.2
        # One admitted call; the second pool entry was never dispatched.
        assert len(store._items) == 1
        (invocation,) = list(store._items.values())
        assert invocation.status is InvocationStatus.UNKNOWN
        assert invocation.error == "TimeoutError"
        assert invocation.finished_at is not None

    async def test_transport_timeout_with_budget_remaining_is_not_a_mechanical_stop(self):
        """stop-4c: the degenerate path — a transport's own TimeoutError
        raised while wall-clock budget *remains* (e.g. a provider-side
        connection timeout under a 60s ceiling) re-raises unchanged: it
        records an intervention and the walk continues, and only a real clock
        expiry surfaces as the designed mechanical stop."""
        calls = _per_model_calls(
            {
                "frontier/max": _scripted_call(
                    {
                        "Cover alpha and beta": TimeoutError("connection timed out"),
                        "Cover gamma": _answered("gamma"),
                    }
                ),
                "free/mini": _scripted_call(
                    {
                        "Cover alpha and beta": _answered("alpha beta"),
                        "Cover gamma": _answered("gamma"),
                    }
                ),
            }
        )
        store = InMemoryInvocationStore()
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_model_calls=8),
            arms=[ArmPolicy(arm_id="frontier", model="frontier/max")],
            make_model_call=calls,
            store=store,
        )
        frontier = report.arms[0]
        assert frontier.attempts == 2  # the walk continued past the failure
        assert frontier.interventions == 1
        (failed,) = [rec for rec in frontier.attempts_log if rec.objective_id == "obj-1"]
        assert failed.intervention is True
        assert failed.intervention_reason == "connection timed out"
        assert frontier.verified_progress == 1  # obj-2 still scored
        assert frontier.stop_reason is None  # no ceiling fired: not a stop
        by_status = {invocation.status: invocation for invocation in store._items.values()}
        assert InvocationStatus.UNKNOWN in by_status
        assert by_status[InvocationStatus.UNKNOWN].error == "connection timed out"
        assert InvocationStatus.COMPLETED in by_status

    async def test_stops_at_objective_ceiling(self):
        """stop-5: max_objectives bounds how much of the pool an arm walks."""
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_objectives=1),
            make_model_call=self._three_answer_calls(),
        )
        for arm in report.arms:
            assert arm.objectives_attempted == 1
            assert arm.attempts == 1
            assert arm.stop_reason is not None
            assert arm.stop_reason.ceiling == "max_objectives"

    def test_dispatch_gate_refuses_a_spent_budget(self):
        """stop-6: enforcement lives in the dispatch seam itself — a budget
        that already reached a ceiling raises rather than dispatching."""
        budget = BudgetState(CampaignCeilings(max_model_calls=1))
        budget.admit_call()  # nothing charged yet: admitted
        budget.charge(InvocationUsage(input_units=1, output_units=1))
        with pytest.raises(BudgetExhausted):
            budget.admit_call()

    def test_dispatch_gate_refuses_when_measured_evidence_is_absent(self):
        """stop-7: a measured ceiling with absent evidence fails closed — the
        charge halts the budget and the dispatch seam refuses the next call
        instead of spending the whole pool against a ceiling that cannot fire."""
        budget = BudgetState(CampaignCeilings(max_spend_usd=5.0))
        budget.admit_call()
        budget.charge(None)  # provider reported nothing: spend cannot advance
        with pytest.raises(BudgetExhausted) as excinfo:
            budget.admit_call()
        assert excinfo.value.stop.ceiling == "max_spend_usd"
        assert excinfo.value.stop.evidence_missing is True

    async def test_spend_ceiling_without_pricing_stops_after_one_call(self):
        """stop-8: a spend-only campaign run without pricing cannot measure
        spend, so the walk stops at the first unmeasured call rather than
        dispatching the entire pool."""
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_spend_usd=5.0),
            pricing=lambda arm: None,
            make_model_call=self._three_answer_calls(),
        )
        for arm in report.arms:
            assert arm.attempts == 1
            assert arm.stop_reason is not None
            assert arm.stop_reason.ceiling == "max_spend_usd"
            assert arm.stop_reason.evidence_missing is True

    async def test_token_ceiling_without_reported_usage_stops_after_one_call(self):
        """stop-9: a token-only campaign whose provider omits usage cannot
        advance its token counter — the walk halts instead of running on."""
        unmeasured = _answered("alpha", inp=0, out=0)
        unmeasured = unmeasured.model_copy(update={"usage_reported": False})
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_total_tokens=1000),
            make_model_call=lambda arm: _scripted_call(
                {"t1": unmeasured, "t2": unmeasured, "t3": unmeasured}
            ),
            pricing=lambda arm: None,
        )
        for arm in report.arms:
            assert arm.attempts == 1
            assert arm.stop_reason is not None
            assert arm.stop_reason.ceiling == "max_total_tokens"
            assert arm.stop_reason.evidence_missing is True

    async def test_spent_arm_does_not_silently_consume_the_other_arm(self):
        """stop-1: arms stop independently — one arm's ceiling must not erase
        or truncate the other arm's record."""
        report = await _run(
            self._three_objective_pool(),
            CampaignCeilings(max_spend_usd=0.005),
            make_model_call=self._three_answer_calls(),
        )
        frontier, baseline = report.arms
        assert frontier.attempts == 1
        assert baseline.attempts == 3
        assert baseline.stop_reason is None  # never hit a ceiling: pool done
        # The arm records stay intact, but with divergent objective coverage
        # the cross-arm comparison is refused, not silently partial.
        assert report.comparison is None


# -- track-1..5: canonical Invocation / cost tracking -------------------------


class TestCanonicalTracking:
    async def test_every_dispatch_is_a_completed_canonical_invocation(self):
        """track-1: every model call traverses the canonical Invocation seam."""
        store = InMemoryInvocationStore()
        await _run(_two_objective_pool(), CampaignCeilings(max_model_calls=10), store=store)

        invocations = list(store._items.values())
        assert len(invocations) == 4  # 2 arms x 2 objectives
        for invocation in invocations:
            assert invocation.status is InvocationStatus.COMPLETED
            assert invocation.finished_at is not None
            assert invocation.workspace_id == WS
            assert invocation.project_id == PROJ
            assert invocation.binding.capability == "model.chat"
            assert invocation.run_id == "run-c1"
            assert invocation.node_run_id.startswith(("frontier:", "baseline:"))
            assert invocation.usage is not None
            assert invocation.usage.input_units == 10
            assert invocation.usage.output_units == 5
            assert invocation.usage.model_version == "max-2026"

    async def test_usage_is_charged_to_the_quota_ledger_exactly_once(self):
        """track-2: the canonical recorder charges each Invocation once, and a
        re-record (terminalization retry) cannot double-charge."""
        store = InMemoryInvocationStore()
        tracker = InMemoryQuotaTracker()
        await _run(
            _two_objective_pool(),
            CampaignCeilings(max_model_calls=10),
            store=store,
            quota_tracker=tracker,
        )

        key = ("frontier/max", cycle_key(CYCLE))
        assert tracker._usage[key]["request_count"] == 2
        assert tracker._usage[key]["input_tokens"] == 20
        assert tracker._usage[key]["output_tokens"] == 10

        from maistro.quota.recorder import CanonicalInvocationUsageRecorder

        recorder = CanonicalInvocationUsageRecorder(InMemoryUsageLog(), tracker)
        for invocation in list(store._items.values()):
            if invocation.status is InvocationStatus.COMPLETED:
                await recorder.record(invocation)
        assert tracker._usage[key]["request_count"] == 2  # unchanged: idempotent

    async def test_cost_is_computed_from_registry_pricing(self):
        """track-3: cost attribution comes from registry metadata via the
        canonical compute path; a free baseline shows a defined zero."""
        report = await _run(_two_objective_pool(), CampaignCeilings(max_model_calls=10))
        frontier = report.arms[0]
        # per call: 10 @ 30c/1k + 5 @ 60c/1k = 0.6 cents = $0.006
        assert frontier.cost_usd == pytest.approx(0.012)
        assert report.comparison is not None
        assert report.comparison.frontier_cost_usd == pytest.approx(0.012)
        assert report.comparison.baseline_cost_usd == 0.0
        # The multiple is undefined against a zero-cost floor — absent, not 0.
        assert report.comparison.cost_multiple is None

    async def test_missing_provider_usage_is_unreported_not_zero(self):
        """track-4 (#718): a provider that reports no usage is recorded as
        absent evidence — token/cost totals stay at zero and do not read as a
        complete free call."""
        reported_none = {
            "Cover alpha and beta": ModelCallResult(content="alpha beta"),
            "Cover gamma": ModelCallResult(content="gamma"),
        }
        tracker = InMemoryQuotaTracker()
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_model_calls=10),
            make_model_call=_per_model_calls(
                {
                    "frontier/max": _scripted_call(reported_none),
                    "free/mini": _scripted_call(reported_none),
                }
            ),
            quota_tracker=tracker,
        )
        frontier = report.arms[0]
        assert frontier.input_tokens == 0
        assert frontier.output_tokens == 0
        assert frontier.cost_usd == 0.0
        # Incomplete evidence must not present a measured ratio.
        usage = await tracker.get_usage_pct("frontier/max", CYCLE, free_tokens=1_000_000)
        assert usage is None

    async def test_failed_dispatch_persists_ambiguous_invocation_without_charging(self):
        """track-5: a hard failure terminalizes its Invocation as UNKNOWN —
        canonical audit evidence (capabilities.invocation._run_provider: a
        generic provider exception cannot prove the effect was unapplied, so
        the row never reads as safe-to-retry FAILED); the quota ledger is not
        charged for a call whose usage never arrived, and the attempt counts
        as an intervention."""
        store = InMemoryInvocationStore()
        tracker = InMemoryQuotaTracker()
        script: dict[str, Any] = {
            "Cover alpha and beta": RuntimeError("gateway 503"),
            "Cover gamma": _answered("gamma", inp=1, out=1),
        }
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_model_calls=10),
            store=store,
            quota_tracker=tracker,
            make_model_call=_per_model_calls(
                {"frontier/max": _scripted_call(script), "free/mini": _scripted_call(script)}
            ),
        )
        frontier = report.arms[0]
        ambiguous = [
            inv
            for inv in store._items.values()
            if inv.status is InvocationStatus.UNKNOWN and inv.node_run_id.startswith("frontier:")
        ]
        assert len(ambiguous) == 1
        assert "gateway 503" in (ambiguous[0].error or "")
        assert ambiguous[0].finished_at is not None
        # No FAILED row exists either: the dispatch error is ambiguous, not a
        # proven-unapplied effect, so nothing may read as safe-to-retry.
        assert not [
            inv
            for inv in store._items.values()
            if inv.status is InvocationStatus.FAILED and inv.node_run_id.startswith("frontier:")
        ]
        # The successful gamma call charged; the failed alpha call did not.
        assert frontier.attempts == 2
        assert frontier.interventions == 1
        assert frontier.intervention_rate == pytest.approx(0.5)
        assert frontier.input_tokens == 1  # only the successful call's usage
        rec = next(a for a in frontier.attempts_log if a.objective_id == "obj-1")
        assert rec.intervention is True
        assert rec.intervention_reason is not None
        key = ("frontier/max", cycle_key(CYCLE))
        assert tracker._usage[key]["request_count"] == 1  # gamma only


# -- compare-1..4: frontier vs cheaper baseline on the same pool --------------


class TestArmComparison:
    async def test_arms_walk_the_identical_pool(self):
        """compare-1: the comparison can never be confounded by differing
        objective sets — both arms' attempt logs cover the same ids in order."""
        report = await _run(_two_objective_pool(), CampaignCeilings(max_model_calls=10))
        frontier_ids = [a.objective_id for a in report.arms[0].attempts_log]
        baseline_ids = [a.objective_id for a in report.arms[1].attempts_log]
        assert frontier_ids == baseline_ids == ["obj-1", "obj-2"]

    async def test_comparison_counts_wins_and_score_delta(self):
        """compare-2: a frontier arm beating the baseline on the shared pool
        is visible as wins, ties, and a positive mean score delta."""
        strong = _scripted_call(
            {
                "Cover alpha and beta": _answered("alpha beta gamma"),
                "Cover gamma": _answered("gamma"),
            }
        )
        weak = _scripted_call(
            {
                "Cover alpha and beta": _answered("only alpha"),
                "Cover gamma": _answered("nothing"),
            }
        )
        report = await run_campaign(
            run_id="run-cmp",
            pool=_two_objective_pool(),
            arms=_arms(),
            ceilings=CampaignCeilings(max_model_calls=10),
            make_model_call=_per_model_calls({"frontier/max": strong, "free/mini": weak}),
            store=InMemoryInvocationStore(),
            usage_log=InMemoryUsageLog(),
            quota_tracker=InMemoryQuotaTracker(),
            pricing=_pricing,
            workspace_id=WS,
            project_id=PROJ,
        )
        comparison = report.comparison
        assert comparison is not None
        assert comparison.frontier_arm == "frontier"
        assert comparison.baseline_arm == "baseline"
        assert comparison.objectives_compared == 2
        assert comparison.frontier_wins == 2
        assert comparison.baseline_wins == 0
        assert comparison.ties == 0
        assert comparison.mean_score_delta == pytest.approx(0.75)

    async def test_early_stopped_arm_refuses_the_comparison(self):
        """compare-2b: when one arm stops early on a ceiling and its attempt
        log covers fewer objectives than its peer, the comparison is refused
        instead of silently scoring the shared prefix."""
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_spend_usd=0.005),  # frontier can afford one call
        )
        assert report.arms[0].attempts == 1
        assert report.arms[1].attempts == 2
        assert report.comparison is None

    async def test_regression_when_frontier_loses_to_baseline(self):
        """compare-3: an experimental arm scoring below its peer on a shared
        objective is recorded as a regression on that arm."""
        weak = _scripted_call({"Cover alpha and beta": _answered("...")})
        strong = _scripted_call({"Cover alpha and beta": _answered("alpha beta")})
        report = await run_campaign(
            run_id="run-reg",
            pool=_pool(
                Objective(
                    objective_id="obj-1",
                    task="Cover alpha and beta",
                    keywords=("alpha", "beta"),
                )
            ),
            arms=_arms(),
            ceilings=CampaignCeilings(max_model_calls=10),
            make_model_call=_per_model_calls({"frontier/max": weak, "free/mini": strong}),
            store=InMemoryInvocationStore(),
            usage_log=InMemoryUsageLog(),
            quota_tracker=InMemoryQuotaTracker(),
            pricing=_pricing,
            workspace_id=WS,
            project_id=PROJ,
        )
        assert report.arms[0].regressions == 1
        assert report.arms[1].regressions == 0
        assert report.comparison is not None
        assert report.comparison.baseline_wins == 1

    async def test_single_arm_report_has_no_comparison(self):
        """compare-4: with one arm there is nothing to compare against, and
        that is recorded honestly rather than fabricated."""
        report = await _run(
            _two_objective_pool(),
            CampaignCeilings(max_model_calls=10),
            arms=[ArmPolicy(arm_id="frontier", model="frontier/max")],
        )
        assert report.comparison is None
        assert len(report.arms) == 1


# -- report-1..3: verified progress, cost, attempts, artifact -----------------


class TestReporting:
    async def test_report_records_progress_attempts_and_serializes(self):
        """report-1: verified progress and attempts are recorded and the
        report is a serializable artifact (round-trips through JSON)."""
        report = await _run(_two_objective_pool(), CampaignCeilings(max_model_calls=10))
        frontier = report.arms[0]
        assert frontier.attempts == 2
        assert frontier.verified_progress == 2  # every keyword matched
        assert frontier.scores == {"obj-1": 1.0, "obj-2": 1.0}
        assert frontier.intervention_rate == 0.0
        assert report.started_at <= report.finished_at
        assert report.ceilings.max_model_calls == 10  # the report echoes policy

        restored = CampaignReport.model_validate_json(report.to_json())
        assert restored.arms[0].verified_progress == 2
        assert restored.comparison == report.comparison

    async def test_partial_keyword_match_is_not_verified_progress(self):
        """report-1: progress below the threshold is scored but not credited."""
        script = {
            "Cover alpha and beta": _answered("only alpha here", inp=1, out=1),
        }
        report = await _run(
            _pool(
                Objective(
                    objective_id="obj-1",
                    task="Cover alpha and beta",
                    keywords=("alpha", "beta"),
                )
            ),
            CampaignCeilings(max_model_calls=10),
            arms=[ArmPolicy(arm_id="frontier", model="frontier/max")],
            make_model_call=_per_model_calls({"frontier/max": _scripted_call(script)}),
        )
        arm = report.arms[0]
        assert arm.scores == {"obj-1": pytest.approx(0.5)}
        assert arm.verified_progress == 0

    async def test_empty_keyword_objective_scores_on_response_presence(self):
        """report-2: the default scorer treats any non-empty response as work
        done for an objective that declares no keywords."""
        assert (
            keyword_objective_scorer(Objective(objective_id="o", task="t"), "some response") == 1.0
        )
        assert keyword_objective_scorer(Objective(objective_id="o", task="t"), "   ") == 0.0

    async def test_scope_refusals_are_recorded_on_the_report(self):
        """report-3: work-scope refusals appear on the campaign artifact."""
        pool = _pool(Objective(objective_id="bad", task="x", paths=("elsewhere/",)))
        report = await _run(pool, CampaignCeilings(allowed_paths=("src/",)))
        assert report.scope_refusals == 2


# -- pool validation -----------------------------------------------------------


class TestObjectivePool:
    def test_empty_pool_is_refused_at_admission(self):
        pool = ObjectivePool(objectives=())
        with pytest.raises(ValueError, match="cannot be empty"):
            ensure_unique_objectives(pool)

    def test_duplicate_objective_ids_are_refused_at_admission(self):
        pool = _pool(
            Objective(objective_id="dup", task="a"),
            Objective(objective_id="dup", task="b"),
        )
        with pytest.raises(ValueError, match="unique"):
            ensure_unique_objectives(pool)

    async def test_run_refuses_a_pool_with_duplicate_ids(self):
        pool = _pool(
            Objective(objective_id="dup", task="a"),
            Objective(objective_id="dup", task="b"),
        )
        with pytest.raises(ValueError, match="unique"):
            await _run(pool, CampaignCeilings(max_model_calls=1))

    def test_blank_objective_text_is_refused(self):
        with pytest.raises(ValidationError):
            Objective(objective_id=" ", task="t")


# -- transport adapter + CLI wiring -------------------------------------------


class TestGatewayModelCall:
    async def test_gateway_transport_captures_reported_usage_and_version(self, monkeypatch):
        """The real transport (make_gateway_llm_call) reports usage through the
        on_response seam; the adapter must carry tokens and the served model
        version into ModelCallResult so the canonical Invocation gets them."""
        captured: dict[str, object] = {}

        def fake_factory(model, *, timeout=60.0, on_response=None):
            captured["model"] = model

            async def inner(messages, *, temperature=0.2, max_tokens=2048):
                assert on_response is not None
                on_response(
                    {
                        "model": "frontier/max-2026-08",
                        "choices": [{"message": {"content": "alpha beta"}}],
                        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                    },
                    object(),
                )
                return "alpha beta"

            return inner

        import maistro_rsi.gateway as gateway_module

        monkeypatch.setattr(gateway_module, "make_gateway_llm_call", fake_factory)
        call = gateway_model_call("frontier/max")
        result = await call([{"role": "user", "content": "t"}])
        assert captured["model"] == "frontier/max"
        assert result.content == "alpha beta"
        assert result.usage_reported is True
        assert result.input_tokens == 11
        assert result.output_tokens == 7
        assert result.model_version == "frontier/max-2026-08"

    async def test_gateway_transport_without_usage_is_absent_evidence(self, monkeypatch):
        """No usage object in the response body reads as unreported, never as
        measured zeros (#718)."""

        def fake_factory(model, *, timeout=60.0, on_response=None):
            async def inner(messages, *, temperature=0.2, max_tokens=2048):
                assert on_response is not None
                on_response({"choices": [{"message": {"content": "hi"}}]}, object())
                return "hi"

            return inner

        import maistro_rsi.gateway as gateway_module

        monkeypatch.setattr(gateway_module, "make_gateway_llm_call", fake_factory)
        result = await gateway_model_call("m")([{"role": "user", "content": "t"}])
        assert result.usage_reported is False
        assert result.input_tokens == 0
        assert result.model_version == ""


class TestCampaignCli:
    def _parse(self, *argv: str) -> Any:
        from maistro_rsi.campaign_cli import build_parser

        return build_parser().parse_args(list(argv))

    def test_parser_accepts_campaign_flags(self):
        args = self._parse(
            "--objective-pool",
            "pool.json",
            "--frontier-model",
            "frontier/max",
            "--baseline-model",
            "openrouter/free",
            "--max-spend-usd",
            "5.0",
            "--max-model-calls",
            "40",
            "--allowed-path",
            "src/",
            "--allowed-path",
            "docs/",
            "--report",
            "out.json",
        )
        assert args.frontier_model == "frontier/max"
        assert args.baseline_model == "openrouter/free"
        assert args.allowed_path == ["src/", "docs/"]

    def test_cli_ceilings_refuse_an_unbounded_campaign(self):
        """The CLI maps flags onto the same ceilings model, so an operator who
        passes no ceiling gets the same refusal a library caller gets."""
        from maistro_rsi.campaign_cli import _campaign_ceilings

        args = self._parse("--objective-pool", "p.json", "--frontier-model", "m")
        with pytest.raises(ValueError, match="at least one explicit ceiling"):
            _campaign_ceilings(args)

    def test_cli_ceilings_refuse_an_infinite_ceiling(self):
        """cli-6: ``--max-seconds inf`` parses to ``float('inf')`` at the
        argparse layer, so the ceilings model — not the parser — must refuse
        it: an admitted infinity would read as a bounded campaign whose stop
        can never fire."""
        from maistro_rsi.campaign_cli import _campaign_ceilings

        args = self._parse(
            "--objective-pool", "p.json", "--frontier-model", "m", "--max-seconds", "inf"
        )
        with pytest.raises(ValidationError, match="should be a finite number"):
            _campaign_ceilings(args)

    def test_cli_ceilings_carry_every_axis(self):
        from maistro_rsi.campaign_cli import _campaign_ceilings

        args = self._parse(
            "--objective-pool",
            "p.json",
            "--frontier-model",
            "m",
            "--max-spend-usd",
            "3.5",
            "--max-total-tokens",
            "1000",
            "--max-model-calls",
            "9",
            "--max-seconds",
            "600",
            "--max-objectives",
            "4",
            "--allowed-path",
            "src/",
        )
        ceilings = _campaign_ceilings(args)
        assert ceilings.max_spend_usd == 3.5
        assert ceilings.max_total_tokens == 1000
        assert ceilings.max_model_calls == 9
        assert ceilings.max_wall_clock_s == 600
        assert ceilings.max_objectives == 4
        assert ceilings.allowed_paths == ("src/",)

    async def test_unconfigured_gateway_refuses_to_dispatch(self, monkeypatch, tmp_path):
        """A campaign without a configured gateway refuses rather than
        fabricating responses — bounded spend over fake answers is worthless."""
        import maistro_rsi.campaign_cli as cli_module

        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps({"objectives": [{"objective_id": "o1", "task": "t"}]}),
            encoding="utf-8",
        )
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        monkeypatch.delenv("LITELLM_URL", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        args = self._parse(
            "--objective-pool",
            str(pool_file),
            "--frontier-model",
            "m",
            "--max-model-calls",
            "1",
        )
        assert await cli_module._run_campaign(args) == 2

    @staticmethod
    def _gateway_env(monkeypatch: Any, *, base_url: str | None, api_key: str | None) -> None:
        """Pin every gateway alias under monkeypatch.

        ``normalize_litellm_env`` writes the values it resolves back to ALL
        aliases; without pinning them here a configured run would leak real
        values into the process environment for every later test.
        """
        for name in (
            "LITELLM_BASE_URL",
            "LITELLM_URL",
            "LITELLM_PROXY_URL",
            "LITELLM_MASTER_KEY",
            "LITELLM_PROXY_KEY",
            "LITELLM_API_KEY",
            "LITELLM_VIRTUAL_KEY",
        ):
            monkeypatch.setenv(name, "")
        if base_url is not None:
            monkeypatch.setenv("LITELLM_BASE_URL", base_url)
        if api_key is not None:
            monkeypatch.setenv("LITELLM_MASTER_KEY", api_key)

    @staticmethod
    def _scripted_gateway(monkeypatch: Any, per_model: dict[str, Any]) -> None:
        import maistro_rsi.campaign_cli as cli_module

        monkeypatch.setattr(
            cli_module,
            "gateway_model_call",
            lambda model, *, timeout: per_model[model],
        )

    async def test_campaign_run_charges_a_quota_ledger(self, monkeypatch, tmp_path):
        """cli-7: the shipped composition wires a quota ledger into the
        canonical recorder, so real CLI dispatches are charged exactly once
        per Invocation identity — not only to the usage log that dies with
        the process. The tracker the CLI builds is observed through the same
        ``record_invocation`` seam the recorder calls."""
        import maistro_rsi.campaign_cli as cli_module

        charged: list[tuple[str, str, int, int]] = []

        class ChargingTracker(InMemoryQuotaTracker):
            async def record_invocation(
                self,
                invocation_id: str,
                provider: str,
                billing_cycle: str,
                input_tokens: int,
                output_tokens: int,
                usage_reported: bool,
            ) -> dict[str, object]:
                charged.append((invocation_id, provider, input_tokens, output_tokens))
                return await super().record_invocation(
                    invocation_id,
                    provider,
                    billing_cycle,
                    input_tokens,
                    output_tokens,
                    usage_reported,
                )

        monkeypatch.setattr(cli_module, "InMemoryQuotaTracker", ChargingTracker)
        self._gateway_env(monkeypatch, base_url="http://gateway.local", api_key="key-test")
        self._scripted_gateway(
            monkeypatch,
            {
                "frontier/max": _scripted_call({"Cover alpha": _answered("alpha")}),
                "free/mini": _scripted_call({"Cover alpha": _answered("alpha free")}),
            },
        )
        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps(
                {
                    "objectives": [
                        {"objective_id": "obj-1", "task": "Cover alpha", "keywords": ["alpha"]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        args = self._parse(
            "--objective-pool",
            str(pool_file),
            "--frontier-model",
            "frontier/max",
            "--baseline-model",
            "free/mini",
            "--max-model-calls",
            "4",
        )
        assert await cli_module._run_campaign(args) == 0
        # Two arms x one objective: every completed Invocation hit the ledger
        # exactly once, with the tokens the provider reported.
        assert len(charged) == 2
        assert len({invocation_id for invocation_id, _, _, _ in charged}) == 2
        assert {provider for _, provider, _, _ in charged} == {"frontier/max", "free/mini"}
        assert all(inp == 10 and out == 5 for _, _, inp, out in charged)

    async def test_campaign_run_dispatches_writes_and_renders(self, monkeypatch, tmp_path, capsys):
        """cli-1: with a configured gateway the CLI dispatches through the
        same ``run_campaign`` seam the library uses — arms, pricing and
        ceilings built from flags, the report artifact written, and the
        per-arm lines plus the frontier-vs-baseline comparison rendered for
        an operator."""
        import maistro_rsi.campaign_cli as cli_module

        self._gateway_env(monkeypatch, base_url="http://gateway.local", api_key="key-test")
        self._scripted_gateway(
            monkeypatch,
            {
                "frontier/max": _scripted_call(
                    {"Cover alpha": _answered("alpha"), "Cover beta": _answered("beta")}
                ),
                "free/mini": _scripted_call(
                    {
                        "Cover alpha": _answered("alpha free"),
                        "Cover beta": _answered("beta free"),
                    }
                ),
            },
        )
        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps(
                {
                    "objectives": [
                        {"objective_id": "obj-1", "task": "Cover alpha", "keywords": ["alpha"]},
                        {"objective_id": "obj-2", "task": "Cover beta", "keywords": ["beta"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        pricing_file = tmp_path / "pricing.json"
        # Only the frontier arm is priced: the baseline's cost stays absent,
        # so the comparison's cost multiple renders as n/a rather than zero.
        pricing_file.write_text(
            json.dumps(
                {
                    "frontier/max": {
                        "provider": "frontier",
                        "cost_per_1k_input": 30.0,
                        "cost_per_1k_output": 60.0,
                    }
                }
            ),
            encoding="utf-8",
        )
        report_file = tmp_path / "out.json"
        args = self._parse(
            "--objective-pool",
            str(pool_file),
            "--frontier-model",
            "frontier/max",
            "--baseline-model",
            "free/mini",
            "--max-model-calls",
            "4",
            "--pricing",
            str(pricing_file),
            "--report",
            str(report_file),
            "--run-id",
            "cli-1",
        )
        assert await cli_module._run_campaign(args) == 0
        payload = json.loads(report_file.read_text(encoding="utf-8"))
        assert payload["run_id"] == "cli-1"
        assert [arm["arm_id"] for arm in payload["arms"]] == ["frontier", "baseline"]
        assert payload["comparison"]["frontier_arm"] == "frontier"
        assert payload["comparison"]["objectives_compared"] == 2
        out = capsys.readouterr().out
        assert "frontier (frontier/max): attempts=2" in out
        assert "baseline (free/mini): attempts=2" in out
        assert "comparison frontier vs baseline over 2 objective(s)" in out
        assert "multiple n/a" in out

    async def test_campaign_cli_prints_json_summary_when_asked(self, monkeypatch, tmp_path, capsys):
        """cli-2: ``--json`` prints exactly the machine-readable artifact —
        the same payload a ``--report`` file would carry, and nothing else
        that a consumer would have to parse around."""
        import maistro_rsi.campaign_cli as cli_module

        self._gateway_env(monkeypatch, base_url="http://gateway.local", api_key="key-test")
        self._scripted_gateway(
            monkeypatch,
            {"frontier/max": _scripted_call({"Cover alpha": _answered("alpha")})},
        )
        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps({"objectives": [{"objective_id": "o1", "task": "Cover alpha"}]}),
            encoding="utf-8",
        )
        args = self._parse(
            "--objective-pool",
            str(pool_file),
            "--frontier-model",
            "frontier/max",
            "--max-model-calls",
            "2",
            "--json",
            "--run-id",
            "cli-json",
        )
        assert await cli_module._run_campaign(args) == 0
        out = capsys.readouterr().out
        # The artifact is pretty-printed over many lines; it starts at the
        # first '{' on stdout and runs to the end.
        payload_text = out[out.index("{") :]
        assert json.loads(payload_text)["run_id"] == "cli-json"

    async def test_campaign_cli_stopped_arm_renders_its_ceiling(
        self, monkeypatch, tmp_path, capsys
    ):
        """cli-3: an arm that stops mid-pool renders the ceiling that stopped
        it, and without ``--report`` the payload goes to stdout."""
        import maistro_rsi.campaign_cli as cli_module

        self._gateway_env(monkeypatch, base_url="http://gateway.local", api_key="key-test")
        self._scripted_gateway(
            monkeypatch,
            {
                "frontier/max": _scripted_call(
                    {"Cover alpha": _answered("alpha"), "Cover beta": _answered("beta")}
                )
            },
        )
        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps(
                {
                    "objectives": [
                        {"objective_id": "obj-1", "task": "Cover alpha", "keywords": ["alpha"]},
                        {"objective_id": "obj-2", "task": "Cover beta", "keywords": ["beta"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        args = self._parse(
            "--objective-pool",
            str(pool_file),
            "--frontier-model",
            "frontier/max",
            "--max-model-calls",
            "1",
            "--run-id",
            "cli-stop",
        )
        assert await cli_module._run_campaign(args) == 0
        out = capsys.readouterr().out
        assert "stop=max_model_calls" in out
        payload_text = out[out.index("{") :]
        assert json.loads(payload_text)["arms"][0]["stop_reason"]["ceiling"] == "max_model_calls"

    def test_cli_module_entry_point_runs_main(self, monkeypatch, tmp_path):
        """cli-4: the console script's module guard routes through ``main()``
        — running the file as ``__main__`` with an unconfigured gateway exits
        2, the designed refusal, so the installed entry wiring is pinned and
        not just the import surface."""
        import maistro_rsi.campaign_cli as cli_module

        self._gateway_env(monkeypatch, base_url=None, api_key=None)
        pool_file = tmp_path / "pool.json"
        pool_file.write_text(
            json.dumps({"objectives": [{"objective_id": "o1", "task": "t"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "maistro-rsi-campaign",
                "--objective-pool",
                str(pool_file),
                "--frontier-model",
                "m",
                "--max-model-calls",
                "1",
            ],
        )
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(Path(cli_module.__file__), run_name="__main__")
        assert excinfo.value.code == 2

    async def test_campaign_cli_reports_invalid_pool_configuration(
        self, monkeypatch, tmp_path, capsys
    ):
        """cli-5: an unreadable pool file is a configuration error reported on
        stderr with exit 2, after the gateway check — never a traceback."""
        import maistro_rsi.campaign_cli as cli_module

        self._gateway_env(monkeypatch, base_url="http://gateway.local", api_key="key-test")
        args = self._parse(
            "--objective-pool",
            str(tmp_path / "absent.json"),
            "--frontier-model",
            "m",
            "--max-model-calls",
            "1",
        )
        assert await cli_module._run_campaign(args) == 2
        assert "invalid campaign configuration" in capsys.readouterr().err
