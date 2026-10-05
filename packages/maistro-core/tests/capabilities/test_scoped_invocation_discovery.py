"""Scoped cursor discovery excludes foreign bodies before decoding bounded pages."""

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore


class Provider:
    name = "provider"
    slot = "model.chat"
    trust_tier = "trusted"


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_scoped_discovery_applies_scope_staleness_cursor_and_limit_before_decode(
    tmp_path, monkeypatch, backend
):
    async with aiosqlite.connect(tmp_path / "pages.sqlite") as conn:
        store = InMemoryInvocationStore() if backend == "memory" else SqliteInvocationStore(conn)
        if backend == "sqlite":
            await store.ensure_schema()
        created = datetime(2020, 1, 1, tzinfo=UTC)
        bound = Binding(
            binding_id="binding", workspace_id="ws", project_id="project", capability="model.chat"
        )
        for ident, status, started in [
            ("a", InvocationStatus.UNKNOWN, None),
            ("b", InvocationStatus.RUNNING, created),
            ("c", InvocationStatus.CREATED, None),
            ("d", InvocationStatus.RUNNING, created + timedelta(hours=2)),
            ("e", InvocationStatus.COMPLETED, None),
            ("foreign", InvocationStatus.UNKNOWN, None),
        ]:
            binding = (
                bound
                if ident != "foreign"
                else bound.model_copy(update={"workspace_id": "other", "project_id": "other"})
            )
            await store.create(
                Invocation(
                    invocation_id=ident,
                    run_id=ident,
                    node_run_id=ident,
                    attempt_id=ident,
                    binding=ResolvedBinding.from_provider(binding, Provider()),
                    effect_key="effect",
                    status=status,
                    created_at=created,
                    started_at=started,
                    finished_at=created
                    if status in {InvocationStatus.UNKNOWN, InvocationStatus.COMPLETED}
                    else None,
                )
            )
        if backend == "sqlite":
            await conn.execute(
                "UPDATE capability_invocations SET payload_json = json_set(payload_json, '$.unexpected', 1) WHERE invocation_id = 'foreign'"
            )
            await conn.commit()
        decoded = []
        original = Invocation.model_validate_json

        def decode(cls, value, **kwargs):
            decoded.append(value)
            return original(value, **kwargs)

        monkeypatch.setattr(Invocation, "model_validate_json", classmethod(decode))

        async def forbidden_global(**_kwargs):
            pytest.fail("operator page must never materialize the global ambiguous ledger")

        monkeypatch.setattr(store, "list_ambiguous", forbidden_global)
        service = InvocationExecutionService(store=store)
        args = {
            "workspace_id": "ws",
            "project_id": "project",
            "stale_before": created + timedelta(hours=1),
            "limit": 2,
        }
        first = await service.discover_ambiguous_page(**args)
        assert [item.invocation_id for item in first] == ["a", "b"]
        assert len(decoded) == (2 if backend == "sqlite" else 0)
        second = await service.discover_ambiguous_page(
            **args, after=(first[-1].created_at, first[-1].invocation_id)
        )
        assert [item.invocation_id for item in second] == ["c"]
        assert len(decoded) == (3 if backend == "sqlite" else 0)
        with pytest.raises(ValueError, match="limit"):
            await service.discover_ambiguous_page(**{**args, "limit": 102})


async def test_operator_discovery_never_falls_back_to_global_only_store():
    class GlobalOnlyStore:
        async def list_ambiguous(self, **_kwargs):
            pytest.fail("unbounded fallback must not be reached")

    service = InvocationExecutionService(store=GlobalOnlyStore())
    with pytest.raises(RuntimeError, match="bounded scoped"):
        await service.discover_ambiguous_page(
            workspace_id="ws", project_id="project", stale_before=datetime.now(UTC)
        )
