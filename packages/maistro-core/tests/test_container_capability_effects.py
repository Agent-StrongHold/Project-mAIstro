"""Backend selection and cross-connection identity for issue #1133."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiosqlite
import pytest

from maistro.capabilities import effect_context
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.effect_context import default_effect_context
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import create_container
from maistro.events.envelope import EventEnvelope, SqliteEventStore
from maistro.types.config import AgentConfig


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1133",
        workspace_id="workspace-1133",
        project_id="project-1133",
        node_id="node-1133",
        capability="agent.spawn_harness",
    )


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-1133"
    slot: str = "agent.spawn_harness"
    trust_tier: str = "trusted"


def _invocation(invocation_id: str) -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id="run-1133",
        node_run_id="node-run-1133",
        attempt_id=invocation_id,
        binding=ResolvedBinding(
            binding_id="binding-1133",
            capability="agent.spawn_harness",
            provider_name="rsi_cycle",
            provider_trust_tier="trusted",
        ),
        effect_key="dispatch:rsi_cycle",
    )


@pytest.mark.asyncio
async def test_sqlite_container_uses_one_durable_effect_event_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "effects.sqlite3"
    config = AgentConfig(
        router_api_key="test-key",
        database_url=f"sqlite:///{database}",
        workspace_id="workspace-1133",
    )
    first = await create_container(config)
    try:
        assert type(first.capability_effects.bindings).__name__ == "SqliteBindingStore"
        assert type(first.capability_effects.invocation_store).__name__ == "SqliteInvocationStore"
        assert isinstance(first.capability_effects.event_store, SqliteEventStore)
        assert first.capability_effects.event_store is not first.durable_event_log
        assert default_effect_context() is first.capability_effects

        await first.capability_effects.bindings.put(_binding())
        await first.capability_effects.event_store.append(
            EventEnvelope(
                type="test.effect",
                workspace_id="workspace-1133",
                run_id="run-1133",
            )
        )
    finally:
        await first.aclose()
    assert default_effect_context() is not first.capability_effects

    second = await create_container(config)
    try:
        assert await second.capability_effects.bindings.get("binding-1133") is not None
        events = await second.capability_effects.event_store.list_stream("workspace:workspace-1133")
        assert [event.type for event in events] == ["test.effect"]
    finally:
        await second.aclose()


@pytest.mark.asyncio
async def test_sqlite_racing_execution_services_dispatch_provider_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "execution-race.sqlite3"
    first_conn = await aiosqlite.connect(database)
    second_conn = await aiosqlite.connect(database)
    first_store = SqliteInvocationStore(first_conn)
    second_store = SqliteInvocationStore(second_conn)
    await first_store.ensure_schema()
    await second_store.ensure_schema()
    calls = 0

    async def resolve(_binding: Binding) -> _Provider:
        return _Provider()

    async def execute(_provider: _Provider, _request: object) -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "committed"

    try:
        outcomes = await asyncio.gather(
            InvocationExecutionService(store=first_store).invoke(
                binding=_binding(),
                run_id="run-race-1133",
                node_run_id="node-race-1133",
                attempt_id="attempt-a",
                effect_key="dispatch:once",
                request={"value": 1},
                resolver=resolve,
                executor=execute,
            ),
            InvocationExecutionService(store=second_store).invoke(
                binding=_binding(),
                run_id="run-race-1133",
                node_run_id="node-race-1133",
                attempt_id="attempt-b",
                effect_key="dispatch:once",
                request={"value": 1},
                resolver=resolve,
                executor=execute,
            ),
            return_exceptions=True,
        )
        assert any(not isinstance(outcome, BaseException) for outcome in outcomes)
        assert calls == 1
        rows = await first_store.list_effect(
            run_id="run-race-1133",
            node_run_id="node-race-1133",
            binding_id="binding-1133",
            effect_key="dispatch:once",
        )
        assert len(rows) == 1
    finally:
        await first_conn.close()
        await second_conn.close()


def test_default_effect_context_is_cached_before_container_configuration() -> None:
    previous = effect_context._process_effect_context
    try:
        effect_context._process_effect_context = None
        first = default_effect_context()
        assert default_effect_context() is first
    finally:
        effect_context._process_effect_context = previous


@pytest.mark.asyncio
async def test_sqlite_logical_invocation_identity_rejects_two_connections(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "race.sqlite3"
    first_conn = await aiosqlite.connect(database)
    second_conn = await aiosqlite.connect(database)
    first = SqliteInvocationStore(first_conn)
    second = SqliteInvocationStore(second_conn)
    await first.ensure_schema()
    await second.ensure_schema()
    try:
        outcomes = await asyncio.gather(
            first.create(_invocation("invocation-a")),
            second.create(_invocation("invocation-b")),
            return_exceptions=True,
        )
        assert sum(not isinstance(outcome, BaseException) for outcome in outcomes) == 1
        rows = await first.list_effect(
            run_id="run-1133",
            node_run_id="node-run-1133",
            binding_id="binding-1133",
            effect_key="dispatch:rsi_cycle",
        )
        assert len(rows) == 1
    finally:
        await first_conn.close()
        await second_conn.close()
