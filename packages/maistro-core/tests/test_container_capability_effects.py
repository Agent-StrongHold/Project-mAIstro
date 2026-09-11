"""Backend selection and cross-connection identity for issue #1133."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.effect_context import default_effect_context
from maistro.capabilities.invocation import Invocation
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import create_container
from maistro.events.envelope import EventEnvelope
from maistro.types.config import AgentConfig


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1133",
        workspace_id="workspace-1133",
        project_id="project-1133",
        node_id="node-1133",
        capability="agent.spawn_harness",
    )


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

    second = await create_container(config)
    try:
        assert await second.capability_effects.bindings.get("binding-1133") is not None
        events = await second.capability_effects.event_store.list_stream("workspace:workspace-1133")
        assert [event.type for event in events] == ["test.effect"]
    finally:
        await second.aclose()


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
