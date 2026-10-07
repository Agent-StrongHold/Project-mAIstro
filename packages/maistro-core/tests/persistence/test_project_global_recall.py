"""Project-changelog recall preserves GLOBAL tenant boundaries (#1247/#1639).

Exercise actual memory, SQLite and configured PostgreSQL stores through the
production Layer 3 path; a predicate-string assertion cannot prove this seam.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
import pytest

from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.persistence.pg_episodic import PgEpisodicStore
from maistro.persistence.sqlite_episodic import SqliteEpisodicStore
from maistro.projects.store import InMemoryProjectStore
from maistro.protocols.memory import EpisodicStore
from maistro.types.memory import EpisodicMemory, MemoryScope, MemoryTier

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def episodic(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[EpisodicStore]:
    if request.param == "memory":
        yield InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        return
    if request.param == "sqlite":
        async with aiosqlite.connect(":memory:") as conn:
            store = SqliteEpisodicStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
            await store.ensure_schema()
            yield store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; no live PostgreSQL proof")
    pg_store = PgEpisodicStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    await pg_store.ensure_schema()
    yield pg_store


def _memory(memory_id: str, **fields: Any) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        content=memory_id,
        project_id=fields.pop("project_id", "project-a"),
        tier=MemoryTier.WISDOM,
        weight=fields.pop("weight", 0.95),
        **fields,
    )


async def _seed(store: EpisodicStore) -> None:
    for memory in (
        _memory("global-a", scope=MemoryScope.GLOBAL, org_id="org-a"),
        _memory("global-b", scope=MemoryScope.GLOBAL, org_id="org-b"),
        _memory("global-public", scope=MemoryScope.GLOBAL),
        _memory("project-agent", scope=MemoryScope.AGENT, agent_id="agent-a", org_id="org-a"),
        _memory("project-user", scope=MemoryScope.USER, user_id="user-a", org_id="org-a"),
        _memory("project-team", scope=MemoryScope.TEAM, team_id="team-a", org_id="org-a"),
        _memory("other-project", scope=MemoryScope.GLOBAL, project_id="project-b"),
        _memory("low-weight", scope=MemoryScope.GLOBAL, weight=0.8),
        _memory("deleted", scope=MemoryScope.GLOBAL, deleted=True),
    ):
        await store.store(memory)


@pytest.mark.parametrize("caller_org", [None, "org-a", "org-b"])
async def test_direct_recall_never_makes_missing_org_a_wildcard(
    episodic: EpisodicStore, caller_org: str | None
) -> None:
    await _seed(episodic)
    rows = await episodic.list_by_scope(project_id="project-a", org_id=caller_org, min_weight=0.9)
    visible_globals = {m.memory_id for m in rows if m.scope == MemoryScope.GLOBAL}
    expected = {"global-public"}
    if caller_org:
        expected.add("global-" + caller_org[-1])
    assert visible_globals == expected


@pytest.mark.parametrize("caller_org", ["", "org-a", "org-b"])
async def test_layer3_keeps_project_history_and_only_authorized_globals(
    episodic: EpisodicStore, caller_org: str
) -> None:
    await _seed(episodic)
    policy = DefaultContextAssemblyPolicy(
        episodic_store=episodic,
        outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
        project_store=InMemoryProjectStore(),
    )
    expected = {"global-public", "project-agent", "project-user", "project-team"}
    if caller_org:
        expected.add("global-" + caller_org[-1])
    text = await policy.layer3(project_id="project-a", org_id=caller_org)
    assert text.splitlines() == sorted(expected)


async def test_layer3_combined_recall_is_deduplicated_ranked_and_bounded(
    episodic: EpisodicStore,
) -> None:
    for memory in (
        _memory("z-global", scope=MemoryScope.GLOBAL, org_id="org-a", weight=0.98),
        _memory("a-public", scope=MemoryScope.GLOBAL, weight=0.96),
        _memory("b-agent", scope=MemoryScope.AGENT, agent_id="agent-a", weight=0.96),
        _memory("c-public", scope=MemoryScope.GLOBAL, weight=0.96),
        _memory("foreign", scope=MemoryScope.GLOBAL, org_id="org-b", weight=0.99),
    ):
        await episodic.store(memory)
    policy = DefaultContextAssemblyPolicy(
        episodic_store=episodic,
        outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
        project_store=InMemoryProjectStore(),
    )
    text = await policy.layer3(project_id="project-a", org_id="org-a", n=3)
    assert text.splitlines() == ["z-global", "a-public", "b-agent"]
