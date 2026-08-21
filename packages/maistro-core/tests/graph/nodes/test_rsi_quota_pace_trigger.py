"""Tests for `rsi.quota_pace_trigger` — pace RSI cycles against real quota headroom."""

from __future__ import annotations

from typing import Any

from maistro.config.settings import (
    MaistroYamlConfig,
    ModelRateProfileConfig,
    RateConstraintConfig,
    set_yaml_config,
)
from maistro.graph.nodes import NodeContext, get_node, list_kinds
from maistro.graph.nodes.rsi_quota_pace_trigger import (
    RsiQuotaPaceTriggerNode,
    RsiQuotaPaceTriggerOut,
)
from maistro.quota.rate_profile import LimitUnit, LimitWindow, ModelRateProfile, RateConstraint
from maistro.quota.usage_log import InMemoryUsageLog


def _ctx(**overrides: Any) -> NodeContext:
    base = {"run_id": "r1", "dag_id": "d1", "node_id": "n1"}
    base.update(overrides)
    return NodeContext(**base)


def test_kind_registered() -> None:
    assert "rsi.quota_pace_trigger" in set(list_kinds())


def test_via_registry_default_constructible() -> None:
    NodeCls = get_node("rsi.quota_pace_trigger")
    instance = NodeCls()
    assert isinstance(instance, RsiQuotaPaceTriggerNode)


async def test_unconfigured_alias_is_unconstrained_time_boxed_only() -> None:
    """No configured rate profile for this alias -- cycles_remaining() reports
    infinite headroom (unified quota model's own fallback), so num_cycles
    collapses to purely the wall-clock-bounded limb."""
    node = RsiQuotaPaceTriggerNode(InMemoryUsageLog(), now_fn=lambda: 1000.0)
    result = await node.run(
        {
            "model_alias": "totally-unconfigured-alias",
            "deadline_epoch_s": 1000.0 + 3600.0,
            "time_per_cycle_s": 600.0,
        },
        _ctx(),
    )
    out: RsiQuotaPaceTriggerOut = result.output
    assert out.num_cycles == 6.0  # 3600s / 600s per cycle, unconstrained by quota
    assert out.harness_type == "rsi_cycle"
    assert out.context["num_cycles"] == 6.0
    assert out.context["model_alias"] == "totally-unconfigured-alias"


async def test_quota_cap_binds_when_tighter_than_time_boxed_cap() -> None:
    profile = ModelRateProfile(
        provider="groq",
        model="groq-kimi-k2",
        constraints=(RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=3),),
    )
    log = InMemoryUsageLog()
    node = RsiQuotaPaceTriggerNode(
        log, rate_profile_resolver=lambda alias: profile, now_fn=lambda: 1000.0
    )
    result = await node.run(
        {
            "model_alias": "groq-kimi-k2",
            "deadline_epoch_s": 1000.0 + 36_000.0,  # plenty of wall-clock time
            "time_per_cycle_s": 60.0,  # time-boxed cap would be 600 cycles
            "requests_per_cycle": 1.0,
        },
        _ctx(),
    )
    # Quota only has 3 requests/day of headroom -> quota_cap=3, far tighter
    # than the 600-cycle time-boxed cap.
    assert result.output.num_cycles == 3.0


async def test_time_boxed_cap_binds_when_tighter_than_quota_cap() -> None:
    profile = ModelRateProfile(
        provider="cerebras",
        model="cerebras-qwen3",
        constraints=(
            RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=14_400),
        ),
    )
    log = InMemoryUsageLog()
    node = RsiQuotaPaceTriggerNode(
        log, rate_profile_resolver=lambda alias: profile, now_fn=lambda: 1000.0
    )
    result = await node.run(
        {
            "model_alias": "cerebras-qwen3",
            "deadline_epoch_s": 1000.0 + 120.0,  # only 2 minutes left
            "time_per_cycle_s": 60.0,  # time-boxed cap = 2 cycles
            "requests_per_cycle": 1.0,
        },
        _ctx(),
    )
    assert result.output.num_cycles == 2.0


async def test_past_deadline_clamps_time_boxed_cap_to_zero() -> None:
    node = RsiQuotaPaceTriggerNode(InMemoryUsageLog(), now_fn=lambda: 2000.0)
    result = await node.run(
        {
            "model_alias": "any-alias",
            "deadline_epoch_s": 1000.0,  # already past
            "time_per_cycle_s": 60.0,
        },
        _ctx(),
    )
    assert result.output.num_cycles == 0.0


async def test_existing_usage_reduces_quota_cap() -> None:
    """`cycles_remaining` reads usage via `UsageSource.count_since(scope_key,
    seconds_ago)` -- no `now` param in that protocol, so it always queries
    against real wall-clock time regardless of this node's injected
    `now_fn` (which only feeds the deadline-math limb). Recorded events
    must therefore use real time.time(), not the fictional clock used
    elsewhere in this file for deadline arithmetic."""
    import time as time_module

    profile = ModelRateProfile(
        provider="groq",
        model="groq-kimi-k2",
        constraints=(RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=10),),
    )
    log = InMemoryUsageLog()
    real_now = time_module.time()
    log.record("groq:groq-kimi-k2", now=real_now - 10)
    log.record("groq:groq-kimi-k2", now=real_now - 5)
    node = RsiQuotaPaceTriggerNode(
        log, rate_profile_resolver=lambda alias: profile, now_fn=lambda: 1000.0
    )
    result = await node.run(
        {
            "model_alias": "groq-kimi-k2",
            "deadline_epoch_s": 1000.0 + 36_000.0,
            "time_per_cycle_s": 1.0,
            "requests_per_cycle": 1.0,
        },
        _ctx(),
    )
    # 10 - 2 already used = 8 remaining, far tighter than the time-boxed cap.
    assert result.output.num_cycles == 8.0


async def test_output_shape_flows_directly_into_spawn_harness_input() -> None:
    """RsiQuotaPaceTriggerOut is shaped to hand off straight into
    agent.spawn_harness's SpawnHarnessIn via a single DAG edge."""
    from maistro.graph.nodes.agent_spawn_harness import SpawnHarnessIn

    node = RsiQuotaPaceTriggerNode(InMemoryUsageLog(), now_fn=lambda: 1000.0)
    result = await node.run(
        {
            "model_alias": "any-alias",
            "deadline_epoch_s": 1000.0 + 3600.0,
            "time_per_cycle_s": 600.0,
        },
        _ctx(),
    )
    spawn_in = SpawnHarnessIn.model_validate(result.output.model_dump())
    assert spawn_in.harness_type == "rsi_cycle"
    assert spawn_in.context["num_cycles"] == 6.0


async def test_base_context_survives_the_handoff_into_a_real_spawn_harness_node() -> None:
    """End-to-end through the durable executor: base_context (e.g. genomes a
    DAG author configured on the trigger node itself) must still be present
    in agent.spawn_harness's context alongside num_cycles -- not clobbered by
    the flat upstream-output-wins merge in _resolve_inputs."""
    from maistro.graph.durable_runs import InMemoryDurableRunStore
    from maistro.graph.nodes import BaseNode, get_node
    from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode

    from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag

    class _FakeAdapter:
        def __init__(self) -> None:
            self.dispatched_context: dict[str, object] | None = None

        async def dispatch(self, request):  # type: ignore[no-untyped-def]
            self.dispatched_context = dict(request.context)
            from maistro.graph.harness import HarnessHandle

            return HarnessHandle(handle_id="h1", harness_type="rsi_cycle")

        async def poll(self, handle):  # type: ignore[no-untyped-def]
            return None

        async def cancel(self, handle):  # type: ignore[no-untyped-def]
            return None

    adapter = _FakeAdapter()

    def _resolver(node_id: str, dag: dict) -> BaseNode:  # type: ignore[type-arg]
        if node_id == "trigger":
            return RsiQuotaPaceTriggerNode(InMemoryUsageLog(), now_fn=lambda: 1000.0)
        if node_id == "spawn":
            return AgentSpawnHarnessNode(adapters={"rsi_cycle": adapter})
        return get_node(dag["kind"])()

    dag = {
        "id": "pace-then-spawn",
        "name": "pace-then-spawn",
        "nodes": [
            {
                "id": "trigger",
                "kind": "rsi.quota_pace_trigger",
                "inputs": {
                    "model_alias": "any-alias",
                    "deadline_epoch_s": 1000.0 + 3600.0,
                    "time_per_cycle_s": 600.0,
                    "base_context": {
                        "baseline_genome": {"id": "g-base"},
                        "candidate_genome": {"id": "g-cand"},
                    },
                },
            },
            {"id": "spawn", "kind": "agent.spawn_harness"},
        ],
        "edges": [{"from_node": "trigger", "to_node": "spawn"}],
        "entry_node": "trigger",
    }

    store = InMemoryDurableRunStore()
    await run_durable_dag(dag, store=store, node_resolver=_resolver)

    assert adapter.dispatched_context is not None
    assert adapter.dispatched_context["num_cycles"] == 6.0
    assert adapter.dispatched_context["baseline_genome"] == {"id": "g-base"}
    assert adapter.dispatched_context["candidate_genome"] == {"id": "g-cand"}


async def test_resolves_rate_profile_via_configured_yaml() -> None:
    """End-to-end with the real config.rate_limits.resolve_rate_profile default
    (not an injected fake resolver), proving Phase 2c's config wiring and
    Phase 5's node actually compose."""
    try:
        set_yaml_config(
            MaistroYamlConfig(
                rate_profiles=[
                    ModelRateProfileConfig(
                        provider="groq",
                        model="groq-kimi-k2",
                        constraints=[
                            RateConstraintConfig(
                                unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=5
                            )
                        ],
                    )
                ]
            )
        )
        node = RsiQuotaPaceTriggerNode(InMemoryUsageLog(), now_fn=lambda: 1000.0)
        result = await node.run(
            {
                "model_alias": "groq-kimi-k2",
                "deadline_epoch_s": 1000.0 + 36_000.0,
                "time_per_cycle_s": 60.0,
                "requests_per_cycle": 1.0,
            },
            _ctx(),
        )
        assert result.output.num_cycles == 5.0
    finally:
        set_yaml_config(None)
