"""The prompt library follows the configured backend (#122).

#122 is "a `postgresql://` DATABASE_URL silently degrades to in-memory stores".
Four stores were wired for it — learnings, outcomes, sessions, audit — and the
prompt manager was not, so `quality/reachability-dispositions.json` kept
`persistence-postgres` at `CONNECT` for `pg_prompts` alone.

The defect was not abstract. `hive-conductor`'s adapter called
`create_container(config)` and then built `InMemoryPromptManager()` by hand,
passing it to `create_agents` beside four container-supplied durable stores. On
PostgreSQL that deployment kept its learnings and lost every prompt on restart,
and the two halves of one call disagreed about whether a database existed.
"""

from __future__ import annotations

import pytest

from maistro.container import Container, _wire_prompt_manager


class _Pool:
    """Stands in for an asyncpg pool. Never connected: `_wire_prompt_manager`
    only chooses, so a test that needed a live server would be testing asyncpg."""


class _Conn:
    """Stands in for the aiosqlite connection `_wire_sqlite_backend` opens."""

    def __init__(self) -> None:
        self.schema_calls = 0


def test_the_container_declares_a_prompt_manager() -> None:
    assert "prompt_manager" in Container.__dataclass_fields__


class TestBackendSelection:
    @pytest.mark.asyncio
    async def test_postgresql_gets_the_postgresql_manager(self) -> None:
        from maistro.persistence.pg_prompts import PgPromptManager

        manager = await _wire_prompt_manager(_Pool(), None)
        assert isinstance(manager, PgPromptManager)

    @pytest.mark.asyncio
    async def test_sqlite_gets_the_sqlite_manager(self, monkeypatch) -> None:
        from maistro.persistence import sqlite_prompts

        prepared: list[object] = []

        class _Recording(sqlite_prompts.SqlitePromptManager):
            async def ensure_schema(self) -> None:
                prepared.append(self)

        monkeypatch.setattr(sqlite_prompts, "SqlitePromptManager", _Recording)
        manager = await _wire_prompt_manager(None, _Conn())
        assert isinstance(manager, _Recording)
        # The SQLite twin owns its schema, so a manager handed back before
        # `ensure_schema()` would fail on the first read rather than at wiring.
        assert prepared == [manager]

    @pytest.mark.asyncio
    async def test_neither_backend_gets_the_in_memory_manager(self) -> None:
        from maistro.prompts.store import InMemoryPromptManager

        manager = await _wire_prompt_manager(None, None)
        assert isinstance(manager, InMemoryPromptManager)

    @pytest.mark.asyncio
    async def test_postgresql_wins_when_both_are_present(self) -> None:
        """The precedence `create_container` applies everywhere else. A
        deployment configured with both must not get a different answer for
        prompts than it gets for learnings."""
        from maistro.persistence.pg_prompts import PgPromptManager

        manager = await _wire_prompt_manager(_Pool(), _Conn())
        assert isinstance(manager, PgPromptManager)


class TestProtocolConformance:
    @pytest.mark.parametrize("backend", ["postgresql", "sqlite", "memory"])
    @pytest.mark.asyncio
    async def test_every_backend_satisfies_the_protocol(self, backend: str) -> None:
        """Whatever the wiring returns is handed straight to `create_agents`,
        which calls `get_with_config` and `upsert` on it. A backend that
        answered the selection correctly and then lacked a method would fail at
        the first agent load instead of here."""
        import aiosqlite

        from maistro.protocols.prompts import PromptManager

        if backend == "sqlite":
            # A real connection, not a stub: this leg runs the twin's own
            # `ensure_schema()`, so a stub would assert that the wiring calls a
            # method rather than that the schema it creates is valid SQL.
            async with aiosqlite.connect(":memory:") as conn:
                manager = await _wire_prompt_manager(None, conn)
                assert isinstance(manager, PromptManager)
            return

        pools = {"postgresql": (_Pool(), None), "memory": (None, None)}[backend]
        manager = await _wire_prompt_manager(*pools)
        assert isinstance(manager, PromptManager)
