"""Regression coverage for issue #55 production composition hardening."""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingDisabled, InMemoryBindingStore
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import InvocationExecutionService
from maistro.container import _wire_capability_effects


class _Provider:
    name = "provider-a"
    slot = "test.capability"
    trust_tier = "trusted"


@pytest.mark.asyncio
async def test_disabled_binding_cannot_be_resolved() -> None:
    store = InMemoryBindingStore()
    await store.put(
        Binding(
            binding_id="disabled",
            workspace_id="ws",
            project_id="project",
            capability="test.capability",
            enabled=False,
        )
    )

    with pytest.raises(BindingDisabled):
        await store.resolve(
            "disabled",
            workspace_id="ws",
            project_id="project",
            node_id="node",
            capability="test.capability",
        )


@pytest.mark.asyncio
async def test_invocation_persists_scope_and_actor_provenance() -> None:
    effects = new_in_memory_effect_context()
    service = InvocationExecutionService(store=effects.invocation_store)
    binding = Binding(
        binding_id="binding-a",
        workspace_id="ws",
        project_id="project",
        capability="test.capability",
        provider_name="provider-a",
    )

    async def resolve(_binding: Binding) -> ResolvedCapabilityProvider:
        return _Provider()

    async def execute(_provider: Any, request: Any) -> dict[str, Any]:
        return {"request": request}

    invocation = await service.invoke(
        binding=binding,
        run_id="run",
        node_run_id="node-run",
        attempt_id="attempt",
        effect_key="effect",
        request={"ok": True},
        actor_id="actor-7",
        resolver=resolve,
        executor=execute,
    )

    assert invocation.status.value == "completed"
    assert invocation.workspace_id == "ws"
    assert invocation.project_id == "project"
    assert invocation.actor_id == "actor-7"
    assert invocation.binding.provider_name == "provider-a"


@pytest.mark.asyncio
async def test_production_sqlite_effect_wiring_selects_durable_quota(tmp_path: Any) -> None:
    db_path = tmp_path / "production-effects.db"
    connection = await aiosqlite.connect(db_path)
    try:
        effects = await _wire_capability_effects(
            pg_pool=None,
            db_pool=connection,
            database_url=f"sqlite:///{db_path}",
        )
        assert effects.quota is not None
        assert type(effects.invocation_store).__name__ == "SqliteInvocationStore"
        assert type(effects.bindings).__name__ == "SqliteBindingStore"
        row = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("invocation_quota_reservations",),
        )
        assert await row.fetchone() == ("invocation_quota_reservations",)
    finally:
        await connection.close()
