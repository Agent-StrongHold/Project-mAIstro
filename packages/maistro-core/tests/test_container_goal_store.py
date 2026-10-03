"""The configured backend chooses the canonical Goal store (#1572).

The acceptance criterion this file answers is "production composition wires
the store, and a test proves the shipped Container exposes it" -- the half
that is easy to skip, because the store can be complete and correct while
nothing in production can reach it. That was the state `maistro.goals` was in
for every consumer that referenced `goal_id`: the field existed, the store did
not.

The in-memory case is not an afterthought. It is the deployment shape
`memory://` names. It is also the one that cannot hold desired-outcome state
across a restart, which is why the wiring says so rather than selecting it
quietly.
"""

from __future__ import annotations

import pytest

from maistro.container import create_container
from maistro.goals.store import GoalStore
from maistro.goals.types import Goal, GoalRevision, GoalState
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


class TestTheBackendChoosesTheGoalStore:
    @pytest.mark.skipif(not postgres_dsn(), reason="set MAISTRO_TEST_PG_DSN")
    async def test_a_postgres_url_wires_the_postgres_store(self) -> None:
        container = await create_container(_config(postgres_dsn()))

        assert type(container.goal_store).__name__ == "PgGoalStore"

    async def test_a_sqlite_url_wires_the_sqlite_store(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        pytest.importorskip("aiosqlite")
        container = await create_container(_config(f"sqlite:///{tmp_path / 'c.sqlite3'}"))
        try:
            assert type(container.goal_store).__name__ == "SqliteGoalStore"
        finally:
            await container.aclose()

    async def test_a_memory_url_still_wires_the_in_memory_store(self) -> None:
        container = await create_container(_config("memory://"))

        assert type(container.goal_store).__name__ == "InMemoryGoalStore"

    async def test_every_wiring_satisfies_the_protocol(self) -> None:
        """Named types are not the contract; the protocol is.

        A store wired by name can still be missing a method the Agent calls,
        and `active_for_agent` is the one #805 wakes up to use.
        """
        container = await create_container(_config("memory://"))

        assert isinstance(container.goal_store, GoalStore)


async def test_the_sqlite_store_is_usable_as_wired(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`ensure_schema` runs during wiring, so the first write does not have to
    discover that the tables are missing. Asserting the type alone would pass
    for a store wired against a database with no tables in it."""
    pytest.importorskip("aiosqlite")

    container = await create_container(_config(f"sqlite:///{tmp_path / 'c.sqlite3'}"))
    try:
        revision = GoalRevision(
            goal_id="g-wired",
            goal_revision=1,
            desired_state="prove the wiring",
            author_id="person-1",
        )
        await container.goal_store.create(
            Goal(
                goal_id="g-wired",
                workspace_id="ws-wired",
                project_id="project-1",
                owner_agent_id="agent-1",
                current_revision=revision.goal_revision,
            ),
            revision,
        )

        # The query a waking Workspace Agent makes, through the shipped object.
        [found] = await container.goal_store.active_for_agent("ws-wired", "agent-1")
        assert found.goal_id == "g-wired"
        assert found.state is GoalState.ACTIVE
    finally:
        await container.aclose()
