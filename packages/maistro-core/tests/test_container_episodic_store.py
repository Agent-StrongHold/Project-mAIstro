"""The configured backend chooses the episodic store (#710).

`create_container` built `InMemoryEpisodicStore()` on a line that sits *after*
the backend branch, so it was what a `postgresql://` deployment got too. Nothing
failed; memory simply did not survive a restart, and two replicas of one
deployment remembered different things.

The in-memory case is not an afterthought here. It is the deployment shape
`memory://` names, and the point of the change is that it becomes a choice
rather than the only outcome.
"""

from __future__ import annotations

import pytest

from maistro.container import create_container
from maistro.persistence import close_pool
from maistro.types.config import AgentConfig

from .persistence.conftest import postgres_dsn

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(autouse=True)
async def _fresh_pool():  # type: ignore[no-untyped-def]
    """`maistro.persistence.get_pool` is a process singleton bound to the loop
    that made it; the same reason `test_container_postgres.py` closes it."""
    await close_pool()
    yield
    await close_pool()


def _config(url: str) -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


class TestTheBackendChoosesTheEpisodicStore:
    @pytest.mark.ac("SPEC-083026-ba26/AC-7")
    @pytest.mark.skipif(not postgres_dsn(), reason="set MAISTRO_TEST_PG_DSN")
    async def test_a_postgres_url_wires_the_postgres_store(self) -> None:
        container = await create_container(_config(postgres_dsn()))

        assert type(container.episodic_store).__name__ == "PgEpisodicStore"

    @pytest.mark.ac("SPEC-083026-ba26/AC-7")
    async def test_a_sqlite_url_wires_the_sqlite_store(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        pytest.importorskip("aiosqlite")
        container = await create_container(_config(f"sqlite:///{tmp_path / 'c.sqlite3'}"))
        try:
            assert type(container.episodic_store).__name__ == "SqliteEpisodicStore"
        finally:
            await container.aclose()

    @pytest.mark.ac("SPEC-083026-ba26/AC-7")
    async def test_a_memory_url_still_wires_the_in_memory_store(self) -> None:
        container = await create_container(_config("memory://"))

        assert type(container.episodic_store).__name__ == "InMemoryEpisodicStore"

    async def test_the_sqlite_store_is_usable_as_wired(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """`ensure_schema` runs during wiring, so the first write does not have
        to discover that the table is missing. Asserting the type alone would
        pass for a store wired against a database with no table in it."""
        pytest.importorskip("aiosqlite")
        from maistro.types.memory import EpisodicMemory, MemoryScope

        container = await create_container(_config(f"sqlite:///{tmp_path / 'c.sqlite3'}"))
        try:
            await container.episodic_store.store(
                EpisodicMemory(
                    memory_id="m1",
                    content="wired",
                    org_id="org-a",
                    scope=MemoryScope.ORGANIZATION,
                )
            )

            [found] = await container.episodic_store.list_by_scope(org_id="org-a")
            assert found.memory_id == "m1"
        finally:
            await container.aclose()
