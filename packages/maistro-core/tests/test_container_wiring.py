"""create_container() wires the PR #216 subsystems (follow-up wiring pass).

Each subsystem merged as a standalone library module (resilience P1, durable
events, LLM providers, observability replay, identity lifecycle, A2A broker,
harness hierarchy, personas, skill import, OAuth) must be constructed,
connected, and reachable on the container.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.types.config import AgentConfig

PERSONA_YAML = Path(__file__).parent / "personas" / "fixtures" / "plant_wellness_local_seller.yaml"


async def _container(**overrides: object) -> Container:
    return await create_container(AgentConfig(router_api_key="test-key", **overrides))  # type: ignore[arg-type]


# --- Exposure ---------------------------------------------------------------


async def test_container_exposes_all_new_subsystems() -> None:
    container = await _container()
    for attr in (
        "resilience_policies",
        "event_bus",
        "durable_event_log",
        "trigger_store",
        "invocation_store",
        "handler_caller",
        "provider_registry",
        "llm_router",
        "record_store",
        "pii_detector",
        "identity_store",
        "token_store",
        "secret_store",
        "harness_registry",
        "hierarchy",
        "golden_record_store",
        "skill_registry",
        "policy_attachment_store",
        "oauth_state_store",
        "identity_linker",
        "harness_adapters",
        "spawn_harness_node",
        "capability_effects",
        "usage_log",
    ):
        assert getattr(container, attr) is not None, f"container.{attr} is not wired"


async def test_sqlite_backend_wires_sqlite_durable_event_stores() -> None:
    container = await _container(database_url="sqlite://")
    assert type(container.elevation_store).__name__ == "SqliteElevationStore"
    assert type(container.usage_log_persistence).__name__ == "SqliteUsageLog"
    assert type(container.durable_event_log).__name__ == "SqliteEventLog"
    assert type(container.trigger_store).__name__ == "SqliteTriggerStore"
    assert type(container.invocation_store).__name__ == "SqliteInvocationStore"
    event = await container.durable_event_log.append("task.created", source="test")
    assert (await container.durable_event_log.get(event.id)) is not None
    container.usage_log.record("provider:model", input_tokens=7, now=1000.0)
    await container.flush_usage_log()
    restored = await container.usage_log_persistence.restore()
    from maistro.quota.rate_profile import LimitUnit

    assert restored.tokens_since("provider:model", 3600, LimitUnit.INPUT_TOKENS, now=1000.0) == 7


# --- Resilience (ADR-066) ----------------------------------------------------


async def test_resilience_policy_store_has_operator_defaults() -> None:
    container = await _container()
    policy = await container.resilience_policies.get("any-agent", "tools", "rate_limit")
    assert policy.max_p1_retries == 5
    refusal = await container.resilience_policies.get("any-agent", "agents", "llm_refusal")
    assert refusal.decide(1, "llm_refusal") == "escalate"


# --- Durable events (ADR-086) -------------------------------------------------


async def test_bus_events_are_bridged_into_the_durable_log() -> None:
    from maistro.events.bus import Event

    container = await _container()
    await container.event_bus.emit(Event(event_type="agent.created", source="test"))
    logged = await container.durable_event_log.query(event_type="agent.created")
    assert len(logged) == 1
    assert logged[0].source == "test"


async def test_process_durable_events_delivers_to_matching_trigger() -> None:
    from maistro.events.trigger_store import TriggerDefinition

    container = await _container()
    delivered = []

    async def _caller(trigger: object, event: object) -> None:
        delivered.append((trigger, event))

    container.handler_caller = _caller
    await container.trigger_store.add(
        TriggerDefinition(trigger_id="t1", name="on-agent", event_pattern="agent.*")
    )
    await container.durable_event_log.append("agent.created")
    cursor = await container.process_durable_events()
    assert len(delivered) == 1
    assert cursor == container.durable_event_cursor > 0

    triggers = await container.list_durable_triggers()
    assert [t.trigger_id for t in triggers] == ["t1"]
    await container.set_durable_trigger_enabled("t1", False)
    assert not (await container.trigger_store.get("t1")).enabled  # type: ignore[union-attr]


def _record_ids_caller(sink: list[int]):
    async def _caller(trigger: object, event: Any) -> None:
        sink.append(event.id)

    return _caller


async def test_durable_event_cursor_survives_a_restart(tmp_path: Path) -> None:
    """#1163: a restart used to replay `durable_event_log` from zero every
    time, because the cursor lived only as a plain `int` on the `Container`.
    A fresh `Container` sharing the same durable SQLite database must instead
    resume from the position the first container's tick durably committed.
    """
    from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID
    from maistro.events.trigger_store import TriggerDefinition

    db_url = f"sqlite:///{tmp_path / 'events.db'}"
    delivered_first: list[int] = []

    container1 = await _container(database_url=db_url)
    try:
        container1.handler_caller = _record_ids_caller(delivered_first)  # type: ignore[assignment]
        await container1.trigger_store.add(
            TriggerDefinition(trigger_id="t1", event_pattern="agent.*")
        )
        await container1.durable_event_log.append("agent.created")
        await container1.durable_event_log.append("agent.created")
        cursor1 = await container1.process_durable_events()
        assert cursor1 == 2
        assert delivered_first == [1, 2]
        # Simulate the old process being gone: its lease is renewed to an
        # already-expired one rather than left at the normal 300s, standing
        # in for however long a real restart takes to notice and wait out.
        await container1.consumer_cursor_store.claim(
            LEGACY_BRIDGE_CONSUMER_ID,
            holder=container1._durable_events_holder,
            lease_seconds=-1.0,
        )
    finally:
        if container1.db_pool is not None:
            await container1.db_pool.close()

    delivered_second: list[int] = []
    container2 = await _container(database_url=db_url)
    try:
        # "Restart": a fresh Container/process (a different holder id), same
        # underlying database, no tick performed yet. The durable position
        # must already read back as 2, not 0 -- proving it is the store, not
        # an in-process default, that answers the claim.
        lease = await container2.consumer_cursor_store.claim(
            LEGACY_BRIDGE_CONSUMER_ID, holder=container2._durable_events_holder
        )
        assert lease is not None
        assert lease.position == 2

        container2.handler_caller = _record_ids_caller(delivered_second)  # type: ignore[assignment]
        await container2.trigger_store.add(
            TriggerDefinition(trigger_id="t1", event_pattern="agent.*")
        )
        await container2.durable_event_log.append("agent.created")  # id 3
        cursor2 = await container2.process_durable_events()

        # Only the new event is redelivered -- restart did not replay ids 1-2.
        assert cursor2 == 3
        assert delivered_second == [3]
    finally:
        if container2.db_pool is not None:
            await container2.db_pool.close()


async def test_a_held_tick_lease_stops_a_second_replica_from_reticking() -> None:
    """#1163: of several replicas that might tick the bridge at once, only
    the lease holder should re-scan/redispatch this round -- ticking under a
    live lease held by someone else must not repeat that work."""
    from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID

    container = await _container()

    other_replica_lease = await container.consumer_cursor_store.claim(
        LEGACY_BRIDGE_CONSUMER_ID, holder="other-replica"
    )
    assert other_replica_lease is not None

    cursor = await container.process_durable_events()

    assert cursor == container.durable_event_cursor == 0


async def test_a_tick_with_nothing_new_does_not_advance_the_stored_cursor() -> None:
    """#1163: `process_durable_events` must not write to the cursor store at
    all when nothing new settled this round (`new_cursor == lease.position`)
    -- only a real advance is worth a write."""
    from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID

    container = await _container()

    cursor = await container.process_durable_events()
    assert cursor == container.durable_event_cursor == 0

    # A second claim (a different holder, after this container's own lease
    # would need to have been renewed/expired) proves the store's own
    # position is still untouched, not just the in-process cache.
    lease = await container.consumer_cursor_store.claim(
        LEGACY_BRIDGE_CONSUMER_ID, holder=container._durable_events_holder
    )
    assert lease is not None
    assert lease.position == 0


class _HidingLog:
    """A durable log whose reads skip chosen ids -- PostgreSQL between a
    `BIGSERIAL` allocation and that append's commit."""

    def __init__(self, inner: Any, hidden: set[int]) -> None:
        self._inner = inner
        self.hidden = hidden

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def query(self, **kwargs: Any) -> Any:
        return [e for e in await self._inner.query(**kwargs) if e.id not in self.hidden]


async def _durable_position(container: Container) -> int:
    from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID

    lease = await container.consumer_cursor_store.claim(
        LEGACY_BRIDGE_CONSUMER_ID, holder=container._durable_events_holder
    )
    assert lease is not None
    return lease.position


async def test_the_durable_cursor_waits_below_an_id_the_log_has_not_committed() -> None:
    """#1163 review: PostgreSQL allocates `BIGSERIAL` ids before commit, so id 3
    can be readable while id 2 is still in an open transaction. Persisting 3
    would exclude 2 from every later ``id > cursor`` read, restart included.
    The durable position must stop at 1 until 2 appears, while the work on 3
    itself is not delayed."""
    from maistro.events.trigger_store import TriggerDefinition

    container = await _container()
    delivered: list[int] = []
    container.handler_caller = _record_ids_caller(delivered)  # type: ignore[assignment]
    await container.trigger_store.add(TriggerDefinition(trigger_id="t1", event_pattern="agent.*"))
    log = _HidingLog(container.durable_event_log, hidden={2})
    container.durable_event_log = log  # type: ignore[assignment]
    for _ in range(3):
        await log.append("agent.created")

    cursor = await container.process_durable_events()

    assert delivered == [1, 3]
    assert cursor == container.durable_event_cursor == 1
    assert await _durable_position(container) == 1

    # The append commits: id 2 becomes readable. The next tick resumes from
    # below it, delivers it, dedupes 3 (already settled), and only now persists 3.
    log.hidden.clear()
    cursor = await container.process_durable_events()

    assert delivered == [1, 3, 2]
    assert cursor == container.durable_event_cursor == 3
    assert await _durable_position(container) == 3


async def test_a_hole_that_outlives_the_grace_is_an_aborted_append() -> None:
    """An id that never commits (the append rolled back) must not pin the
    resume point forever: once the hole has been seen for longer than
    `durable_event_hole_grace_s`, the position moves past it."""
    from maistro.events.trigger_store import TriggerDefinition

    container = await _container()
    delivered: list[int] = []
    container.handler_caller = _record_ids_caller(delivered)  # type: ignore[assignment]
    await container.trigger_store.add(TriggerDefinition(trigger_id="t1", event_pattern="agent.*"))
    log = _HidingLog(container.durable_event_log, hidden={2})
    container.durable_event_log = log  # type: ignore[assignment]
    for _ in range(3):
        await log.append("agent.created")

    assert await container.process_durable_events() == 1
    assert await _durable_position(container) == 1

    # Still within grace on the next tick: the position holds, and 3 is
    # redelivered idempotently (deduped by the invocation store, so no call).
    assert await container.process_durable_events() == 1
    assert delivered == [1, 3]

    # The grace lapses with the hole still open.
    container.durable_event_hole_grace_s = 0.0
    cursor = await container.process_durable_events()

    assert cursor == container.durable_event_cursor == 3
    assert await _durable_position(container) == 3
    assert delivered == [1, 3]


async def test_each_hole_gets_its_own_grace() -> None:
    """Two open appends: the first lapsing must not let the position jump
    past a second hole that was only just noticed."""
    container = await _container()
    container.durable_event_hole_grace_s = 10.0

    # First tick: only hole 2 is visible below the cursor.
    assert container._gap_safe_position(3, (2,), now=100.0) == 1
    # Later tick: 2 is still open (past grace) and a fresh hole at 5 appeared.
    assert container._gap_safe_position(6, (2, 5), now=111.0) == 4
    # Later still: 5 also lapses; the position moves to the cursor.
    assert container._gap_safe_position(6, (2, 5), now=122.0) == 6
    # A hole that fills is forgotten, so a re-opened id restarts its grace.
    assert container._gap_safe_position(6, (), now=123.0) == 6
    assert container._gap_safe_position(6, (2,), now=124.0) == 1


# --- LLM providers (SPEC-070226-cb8d) -----------------------------------------


async def test_llm_router_routes_over_registered_models() -> None:
    from maistro.providers.errors import NoEligibleModelError
    from maistro.providers.types import ModelMetadata, RoutingTask

    container = await _container()
    task = RoutingTask(description="summarize")
    with pytest.raises(NoEligibleModelError):
        await container.llm_router.select(task)

    container.provider_registry.register_model(
        ModelMetadata(
            name="local-small",
            provider="ollama",
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            latency_p50_ms=100,
            tier="fast",
        )
    )
    selected = await container.llm_router.select(task)
    assert selected.name == "local-small"


async def test_provider_config_path_loads_yaml_registry(tmp_path: Path) -> None:
    config_file = tmp_path / "providers.yaml"
    config_file.write_text(
        "models:\n"
        "  - name: yaml-model\n"
        "    provider: openai\n"
        "    cost_input: 1.0\n"
        "    cost_output: 2.0\n"
        "    latency_p50_ms: 300\n",
        encoding="utf-8",
    )
    container = await _container(provider_config_path=str(config_file))
    model = await container.provider_registry.get_model("yaml-model")
    assert model.provider == "openai"


# --- Observability replay (ADR-055) -------------------------------------------


async def test_record_store_and_replay_session_roundtrip() -> None:
    from maistro.observability.replay import ReplayEvent, canonical_request_hash
    from maistro.observability.tiers import SensitivityTier

    container = await _container()
    args = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    await container.record_store.record(
        ReplayEvent(
            trace_id="trace-1",
            span_id="span-1",
            seq=0,
            kind="llm",
            request_hash=canonical_request_hash(args),
            payload={"request": args, "response": {"content": "hello"}},
            tier=SensitivityTier.NORMAL,
        )
    )
    session = container.replay_session("trace-1")
    assert (await session.next_response("llm", args)) == {"content": "hello"}


async def test_pii_detector_redacts_normal_tier_payloads() -> None:
    container = await _container()
    payload = container.pii_detector.inspect({"text": "reach me at bob@example.com"})
    assert "bob@example.com" not in payload["text"]


# --- Identity lifecycle (ADR-084) ---------------------------------------------


async def test_issue_and_verify_capability_token_via_container() -> None:
    container = await _container()
    identity = await container.create_agent_identity("agent-a")
    assert identity.did.startswith("did:key:z")
    token = await container.issue_capability_token("agent-a", "agent-b", "read")
    assert await container.verify_capability_token(token) is True

    from maistro.identity.lifecycle import TokenRevokedError

    await container.token_store.revoke(token)
    with pytest.raises(TokenRevokedError):
        await container.verify_capability_token(token)


# --- A2A broker (ADR-058): retired from the Container (#225) -------------------
#
# `Container.a2a_broker` was constructed, stored and read by nothing but this
# file. The refusal it used to assert here — an unknown calling agent, an
# unknown delegation target — is `A2ABroker`'s own behaviour and keeps its test
# in `tests/a2a/test_broker.py::test_unknown_caller_and_target_refused`, run
# against the class directly. What is gone with the wiring is only the claim
# that the Container offers it, which is the claim that was untrue
# (ADR-082426-6201).


@pytest.mark.ac("ADR-082426-6201/AC-4")
async def test_the_container_offers_no_a2a_broker() -> None:
    """Asserting an absence, deliberately. A retired surface that nothing
    checks comes back the next time someone reaches for a broker and finds the
    old wiring in git history — and it comes back the same way it left, as an
    attribute constructed, stored and read by nobody. `A2ABroker` itself stays
    exported from `maistro.a2a` for downstream products (ADR-019); what must
    stay gone is the Container's claim to offer one."""
    container = await _container()

    assert not hasattr(container, "a2a_broker")


# --- Hierarchy (ADR-101) --------------------------------------------------------


async def test_harness_registry_registration_and_lookup() -> None:
    from maistro.orchestrator.hierarchy import HarnessAdvertisement, HarnessUnavailableError

    container = await _container()
    assert await container.harness_registry.list_harnesses() == []
    with pytest.raises(HarnessUnavailableError):
        await container.harness_registry.get_harness("pi-0")
    container.harness_registry.register(  # type: ignore[attr-defined]
        HarnessAdvertisement(harness_id="pi-0", endpoint="https://pi.local:8000")
    )
    found = await container.harness_registry.get_harness("pi-0")
    assert found.endpoint == "https://pi.local:8000"


# --- Personas (SPEC-192) ---------------------------------------------------------


async def test_golden_record_store_versions_via_container() -> None:
    container = await _container()
    first = await container.golden_record_store.save("persona-x", [], [])
    second = await container.golden_record_store.save("persona-x", [], [])
    assert (first.version, second.version) == (1, 2)
    latest = await container.golden_record_store.get_latest("persona-x")
    assert latest is not None and latest.supersedes == 1
    assert await container.golden_record_store.list_versions("persona-x") == [1, 2]


async def test_persona_scorer_falls_back_to_rubric() -> None:
    container = await _container()
    scorer = container.persona_scorer(str(PERSONA_YAML))
    score = await scorer.score("some output", {})
    assert scorer.provider == "rubric"
    assert 0.0 <= score.value <= 1.0


# --- Skills import (ADR-083) ------------------------------------------------------


async def test_skill_payload_verification_via_container() -> None:
    from maistro.skills.import_pipeline import PolicyAttachment

    container = await _container()
    allowed, reasons = container.verify_skill_payload("unbound-skill", "harmless body")
    assert allowed is False
    assert any("no rescan_on_use policy attachment" in r for r in reasons)

    import hashlib

    payload = "harmless body"
    container.policy_attachment_store.attach(
        PolicyAttachment(
            skill_name="bound-skill",
            content_hash=hashlib.sha256(payload.encode()).hexdigest(),
        )
    )
    allowed, reasons = container.verify_skill_payload("bound-skill", payload)
    assert allowed is True and reasons == ()


# --- Agent-harness DAG node adapters (ADR-062 spawn_harness) ------------------------


async def test_harness_adapters_default_to_empty() -> None:
    container = await _container()
    assert container.harness_adapters == {}


async def test_spawn_harness_node_has_no_adapters_by_default() -> None:
    from maistro.capabilities.binding import Binding
    from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
    from maistro.graph.nodes.base import NodeContext

    container = await _container()
    await container.capability_effects.bindings.put(
        Binding(
            binding_id="b-rsi-no-adapter",
            workspace_id="ws-rsi",
            project_id="p-rsi",
            node_id="n1",
            capability=AgentSpawnHarnessNode.capability,
            provider_name="rsi_cycle",
        )
    )
    result = await container.spawn_harness_node.run(
        {"harness_type": "rsi_cycle", "task": "x", "binding_id": "b-rsi-no-adapter"},
        NodeContext(
            run_id="r1",
            dag_id="d1",
            node_id="n1",
            workspace_id="ws-rsi",
            project_id="p-rsi",
        ),
    )
    # The Binding authorizes the capability, but the container wires no
    # harness adapters by default, so the governed dispatch still fails
    # closed naming the missing provider (#55).
    assert result.success is False
    assert result.error_code == "CapabilityUnavailable"
    assert "rsi_cycle" in (result.error_message or "")


async def test_injected_harness_adapters_reach_the_container_and_the_node() -> None:
    from maistro.capabilities.binding import Binding
    from maistro.graph.harness import HarnessHandle, HarnessRequest, HarnessResult
    from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
    from maistro.graph.nodes.base import NodeContext

    class _FakeAdapter:
        async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
            return HarnessHandle(handle_id="h1", harness_type="rsi_cycle")

        async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
            return HarnessResult(handle_id=handle.handle_id, success=True, output="done")

        async def cancel(self, handle: HarnessHandle) -> None:
            return None

    fake = _FakeAdapter()
    container = await create_container(
        AgentConfig(router_api_key="test-key"), harness_adapters={"rsi_cycle": fake}
    )
    assert container.harness_adapters == {"rsi_cycle": fake}
    await container.capability_effects.bindings.put(
        Binding(
            binding_id="b-rsi-dispatch",
            workspace_id="ws-rsi",
            project_id="p-rsi",
            node_id="n1",
            capability=AgentSpawnHarnessNode.capability,
            provider_name="rsi_cycle",
        )
    )
    result = await container.spawn_harness_node.run(
        {"harness_type": "rsi_cycle", "task": "x", "binding_id": "b-rsi-dispatch"},
        NodeContext(
            run_id="r1",
            dag_id="d1",
            node_id="n1",
            node_run_id="nr1",
            attempt_id="a1",
            workspace_id="ws-rsi",
            project_id="p-rsi",
        ),
    )
    # The adapter dispatch crosses the container's governed Invocation
    # boundary: the pause carries the handle plus the Binding/Invocation ids.
    assert result.status == "paused"
    assert result.metadata["handle_id"] == "h1"
    assert result.metadata["binding_id"] == "b-rsi-dispatch"
    assert result.metadata["invocation_id"]


# --- build_node_resolver (production reachability) --------------------------------


def test_build_node_resolver_resolves_spawn_harness_with_injected_adapters() -> None:
    from maistro.container import build_node_resolver
    from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode

    fake_adapter = object()
    resolver = build_node_resolver(harness_adapters={"rsi_cycle": fake_adapter})  # type: ignore[arg-type]

    dag = {"nodes": [{"id": "n1", "kind": "agent.spawn_harness"}]}
    node = resolver("n1", dag)

    assert isinstance(node, AgentSpawnHarnessNode)
    assert node._adapters == {"rsi_cycle": fake_adapter}


def test_build_node_resolver_resolves_quota_pace_trigger_with_injected_usage_log() -> None:
    from maistro.container import build_node_resolver
    from maistro.graph.nodes.rsi_quota_pace_trigger import RsiQuotaPaceTriggerNode
    from maistro.quota.usage_log import InMemoryUsageLog

    log = InMemoryUsageLog()
    resolver = build_node_resolver(usage_log=log)

    dag = {"nodes": [{"id": "n1", "kind": "rsi.quota_pace_trigger"}]}
    node = resolver("n1", dag)

    assert isinstance(node, RsiQuotaPaceTriggerNode)
    assert node._source is log


def test_build_node_resolver_falls_back_to_the_plain_registry_for_other_kinds() -> None:
    from maistro.container import build_node_resolver
    from maistro.graph.nodes.llm_summarize import LlmSummarizeNode

    resolver = build_node_resolver()
    dag = {"nodes": [{"id": "n1", "kind": "llm.summarize"}]}
    node = resolver("n1", dag)

    assert isinstance(node, LlmSummarizeNode)


def test_build_node_resolver_defaults_pick_up_module_level_singletons() -> None:
    from maistro.container import build_node_resolver
    from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
    from maistro.quota.usage_log import get_default_usage_log

    resolver = build_node_resolver()
    dag = {"nodes": [{"id": "n1", "kind": "agent.spawn_harness"}]}
    node = resolver("n1", dag)

    assert isinstance(node, AgentSpawnHarnessNode)
    assert node._adapters == {}

    from maistro.graph.nodes.rsi_quota_pace_trigger import RsiQuotaPaceTriggerNode

    dag2 = {"nodes": [{"id": "n2", "kind": "rsi.quota_pace_trigger"}]}
    node2 = resolver("n2", dag2)
    assert isinstance(node2, RsiQuotaPaceTriggerNode)
    assert node2._source is get_default_usage_log()


def test_build_node_resolver_raises_for_unknown_node_id() -> None:
    from maistro.container import build_node_resolver

    resolver = build_node_resolver()
    with pytest.raises(KeyError):
        resolver("missing", {"nodes": []})


async def test_container_usage_log_reaches_build_node_resolver() -> None:
    from maistro.container import build_node_resolver
    from maistro.graph.nodes.rsi_quota_pace_trigger import RsiQuotaPaceTriggerNode

    container = await _container()
    resolver = build_node_resolver(
        harness_adapters=container.harness_adapters, usage_log=container.usage_log
    )
    dag = {"nodes": [{"id": "n1", "kind": "rsi.quota_pace_trigger"}]}
    node = resolver("n1", dag)

    assert isinstance(node, RsiQuotaPaceTriggerNode)
    assert node._source is container.usage_log


# --- OAuth (ADR-059) ----------------------------------------------------------------


async def test_oauth_state_store_and_identity_linker_wired() -> None:
    from maistro.auth.oauth import OAuthStateEntry

    container = await _container()
    import time

    entry = OAuthStateEntry(
        provider="github",
        code_verifier="v" * 43,
        redirect_uri="http://localhost/cb",
        nonce="nonce-1",
        expires_at=time.monotonic() + 600,
    )
    await container.oauth_state_store.put("state-1", entry)
    consumed = await container.oauth_state_store.consume("state-1")
    assert consumed is not None and consumed.provider == "github"
    # Single-use: a second consume misses.
    assert await container.oauth_state_store.consume("state-1") is None

    from maistro.auth.oauth import OAuthIdentity

    identity = OAuthIdentity(provider="github", sub="123", email="x@example.com")
    assert await container.identity_linker.resolve_user(identity) is None
    await container.identity_linker.link_current_user(identity, "user-9")
    assert await container.identity_linker.resolve_user(identity) == "user-9"


async def test_oauth_client_factory_builds_client() -> None:
    import httpx

    from maistro.auth.oauth import OAuth2Client, OAuthProviderConfig

    container = await _container()
    async with httpx.AsyncClient() as http:
        client = container.oauth_client(
            {
                "github": OAuthProviderConfig(
                    name="github",
                    authorization_url="https://example.com/authorize",
                    token_url="https://example.com/token",
                    client_id="cid",
                )
            },
            http,
            lambda _name: "secret",
        )
        assert isinstance(client, OAuth2Client)
        url, state = await client.authorize_url("github", "http://localhost/cb")
        assert "code_challenge=" in url and state


# --- crash recovery (ADR-082526-b36a / #232) -----------------------------------


async def test_the_container_sweeps_abandoned_attempts() -> None:
    """The production entry point for lease recovery.

    Wired rather than left as a bare store method, because a public surface
    nobody calls is the shape #225 and #244 are both about: it reads as
    supported while nothing exercises it.
    """
    from datetime import UTC, datetime, timedelta

    from maistro.graph import Graph, Node
    from maistro.runs.model import AttemptStatus, RunStatus

    container = await _container()
    store = container.run_store
    project_id = (await container.project_scope_store.create_root("recovery")).project_id
    graph = Graph(
        workspace_id="recovery",
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run = await store.create_run(graph)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="n1")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_node_run(node_run.node_run_id, status)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-A", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    # Nothing to do while the holder's lease is still live.
    assert await container.recover_abandoned_attempts(now=datetime.now(UTC)) == 0

    swept = await container.recover_abandoned_attempts(now=lease.expires_at + timedelta(seconds=1))

    assert swept == 1
    settled = await store.get_attempt(attempt.attempt_id)
    assert settled is not None
    assert settled.status is AttemptStatus.CANCELLED
    assert "worker-A" in (settled.error or "")


@pytest.mark.ac("ADR-082826-08f0/AC-5")
async def test_the_sweep_parks_the_reclaimed_attempts_logical_records() -> None:
    """Reclaim completes through the lifecycle seam (#462).

    Before this, the sweep terminalized the Attempt and stopped: the NodeRun
    stayed RUNNING and the Run stayed RUNNING forever — non-terminal, so never
    purgeable either. ADR-082526-b36a promised the RECOVERED park; this proves
    the code keeps the promise, and that a second sweep is a no-op.
    """
    from datetime import timedelta

    from maistro.graph import Graph, Node
    from maistro.observability.metrics import registry as metrics_registry
    from maistro.runs.model import AttemptStatus, RunStatus

    container = await _container()
    store = container.run_store
    project_id = (await container.project_scope_store.create_root("recovery-park")).project_id
    graph = Graph(
        workspace_id="recovery-park",
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run = await store.create_run(graph)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="n1")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_node_run(node_run.node_run_id, status)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-B", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after_lapse = lease.expires_at + timedelta(seconds=1)

    assert await container.recover_abandoned_attempts(now=after_lapse) == 1

    settled = await store.get_attempt(attempt.attempt_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    parked_node = await store.get_node_run(node_run.node_run_id)
    assert parked_node is not None and parked_node.status is RunStatus.WAITING
    parked_run = await store.get_run(run.run_id)
    assert parked_run is not None and parked_run.status is RunStatus.WAITING

    # Idempotent: the second tick reclaims nothing and rewrites nothing.
    assert await container.recover_abandoned_attempts(now=after_lapse) == 0
    again_node = await store.get_node_run(node_run.node_run_id)
    assert again_node is not None and again_node.status is RunStatus.WAITING
    again_run = await store.get_run(run.run_id)
    assert again_run is not None and again_run.status is RunStatus.WAITING

    # The tick refreshed the recovery-visibility gauges (#338): the parked Run
    # is non-terminal and counted, with a real age.
    collected = metrics_registry.collect_all()
    (open_runs_sample,) = collected["maistro_non_terminal_runs"]
    assert open_runs_sample["value"] >= 1


async def test_the_sweep_survives_an_attempt_it_cannot_reconcile(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An Attempt the lifecycle seam refuses is logged, not fatal to the tick.

    The state is reachable: a worker claims an Attempt and dies before
    `prepare_execution` moves the NodeRun to RUNNING, leaving a leased Attempt
    under a QUEUED NodeRun. Reclaim settles the physical record; reconciliation
    then refuses to park a NodeRun that never ran — and the sweep must record
    that refusal and finish the tick rather than abort it.
    """
    import logging
    from datetime import timedelta

    from maistro.graph import Graph, Node
    from maistro.runs.model import AttemptStatus, RunStatus

    container = await _container()
    store = container.run_store
    project_id = (await container.project_scope_store.create_root("recovery-skew")).project_id
    graph = Graph(
        workspace_id="recovery-skew",
        project_id=project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run = await store.create_run(graph)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="n1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-C", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    with caplog.at_level(logging.WARNING):
        swept = await container.recover_abandoned_attempts(
            now=lease.expires_at + timedelta(seconds=1)
        )

    assert swept == 1  # the physical Attempt is still reclaimed
    settled = await store.get_attempt(attempt.attempt_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    stuck = await store.get_node_run(node_run.node_run_id)
    assert stuck is not None and stuck.status is RunStatus.QUEUED
    assert "could not be reconciled" in caplog.text


# --- #231: the schedule admitter is wired, not left for callers to build ----


async def test_the_container_wires_a_schedule_admitter() -> None:
    """`ScheduleRunAdmitter` had no production caller and no constructor call.

    #251 found it admitting Runs nothing executed; the other half of the same
    gap is that nothing built it, so the live scheduler grew its own
    create-and-advance logic instead (#231). Built here, from the three stores
    the spine already wires, so a producer cannot hold a different idea of
    what admission means.
    """
    from maistro.scheduling.admission import ScheduleRunAdmitter

    container = await _container()

    assert isinstance(container.schedule_admitter, ScheduleRunAdmitter)


def test_a_container_without_a_template_store_has_no_schedule_admitter() -> None:
    """An admitter that cannot resolve a template cannot admit, so None is the
    honest answer rather than one that raises on first use.

    Asserted on the declared default rather than an instance: `Container` takes
    thirteen required arguments, and a Container assembled by hand — the case
    this default exists for — is exactly the one that never runs
    `create_container`'s wiring.
    """
    import dataclasses

    from maistro.container import Container

    defaults = {f.name: f.default for f in dataclasses.fields(Container)}

    assert defaults["template_store"] is None
    assert defaults["schedule_admitter"] is None


async def test_wiring_declines_to_build_an_admitter_with_no_template_store() -> None:
    """The branch behind that default, executed rather than declared.

    An admitter that cannot resolve a template cannot admit, so the wiring
    returns None instead of constructing one that raises on first use.
    """
    from maistro.container import _wire_schedule_admission

    container = await _container()

    assert _wire_schedule_admission(container.run_store, None, container.schedule_store) is None
    assert (
        _wire_schedule_admission(
            container.run_store, container.template_store, container.schedule_store
        )
        is not None
    )
