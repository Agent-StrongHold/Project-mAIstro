"""The thumbs signal reads the same from every outcome store (#696).

The optimizer's user-satisfaction signal used to be read as
`getattr(store, "_outcomes", [])` -- a private list that `InMemoryOutcomeStore`
has and neither durable store does. Against PostgreSQL or SQLite that
expression returns `[]`, so the signal would have gone empty and nothing would
have raised: the Optimization Inbox would keep rendering, with no thumbs,
forever.

Parametrized over all three stores because "the same query answers the same
way" is the entire claim. The in-memory store is included rather than treated
as a mere double: most of the suite runs against it, so a double that cannot
reproduce the durable stores' answer is a double that hides the difference.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.constants import THUMB_WINDOW_DAYS
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.persistence.pg_outcomes import PgOutcomeStore
from maistro.types.memory import Outcome

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def outcome_store(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[Any]:
    if request.param == "memory":
        yield InMemoryOutcomeStore()
        return
    if request.param == "sqlite":
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteOutcomeStore(conn)
        await store.ensure_schema()
        try:
            yield store
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    yield PgOutcomeStore(pg_pool)


def _thumb(
    thumb: str,
    *,
    dag_id: str = "d1",
    node_id: str = "n1",
    comment: str = "",
    org_id: str = "",
    age_days: int = 0,
) -> Outcome:
    return Outcome(
        task_type="dag_run",
        success=True,
        user_id="u1",
        org_id=org_id,
        dag_id=dag_id,
        node_id=node_id,
        thumb=thumb,
        thumb_comment=comment,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


class TestTheThumbsSignalIsAProtocolQuery:
    @pytest.mark.ac("SPEC-083026-a1f7/AC-1")
    async def test_a_recorded_thumb_comes_back(self, outcome_store: Any) -> None:
        await outcome_store.record(_thumb("up"))

        found = await outcome_store.list_thumbs(dag_id="d1")

        assert [(o.thumb, o.node_id) for o in found] == [("up", "n1")]

    @pytest.mark.ac("SPEC-083026-a1f7/AC-1")
    async def test_the_comment_survives_the_round_trip(self, outcome_store: Any) -> None:
        """The comment is the half the optimizer feeds to the prompt rewriter.

        A store that returned the thumb and dropped its text would satisfy a
        count-only assertion and still lose the only part a human wrote.
        """
        await outcome_store.record(_thumb("down", comment="it invented a citation"))

        found = await outcome_store.list_thumbs(dag_id="d1")

        assert [o.thumb_comment for o in found] == ["it invented a citation"]

    @pytest.mark.ac("SPEC-083026-a1f7/AC-1")
    async def test_an_outcome_with_no_thumb_is_not_a_thumb(self, outcome_store: Any) -> None:
        """Most outcomes are ordinary request records; they are not feedback."""
        await outcome_store.record(_thumb(""))

        assert await outcome_store.list_thumbs(dag_id="d1") == []

    @pytest.mark.ac("SPEC-083026-a1f7/AC-2")
    async def test_another_dags_thumb_is_excluded(self, outcome_store: Any) -> None:
        await outcome_store.record(_thumb("up", dag_id="other"))

        assert await outcome_store.list_thumbs(dag_id="d1") == []

    @pytest.mark.ac("SPEC-083026-a1f7/AC-2")
    async def test_an_unattributed_thumb_belongs_to_every_dag(self, outcome_store: Any) -> None:
        """The rule the optimizer applied inline, kept deliberately.

        A thumb carrying no `dag_id` was recorded before the attribution wire
        existed. Excluding it would tidy the filter by discarding feedback a
        user actually gave, so all three stores include it.
        """
        await outcome_store.record(_thumb("down", dag_id=""))

        found = await outcome_store.list_thumbs(dag_id="d1")

        assert [o.thumb for o in found] == ["down"]

    @pytest.mark.ac("SPEC-083026-a1f7/AC-2")
    async def test_naming_no_dag_returns_every_thumb(self, outcome_store: Any) -> None:
        await outcome_store.record(_thumb("up", dag_id="a"))
        await outcome_store.record(_thumb("down", dag_id="b"))

        found = await outcome_store.list_thumbs()

        assert sorted(o.thumb for o in found) == ["down", "up"]

    @pytest.mark.ac("SPEC-083026-a1f7/AC-5")
    async def test_a_thumb_older_than_the_window_falls_out(self, outcome_store: Any) -> None:
        """Retention is a decision now, not whatever `MAX_OUTCOMES` happened to be."""
        await outcome_store.record(_thumb("up", age_days=THUMB_WINDOW_DAYS + 1))

        assert await outcome_store.list_thumbs(dag_id="d1") == []

    @pytest.mark.ac("SPEC-083026-a1f7/AC-5")
    async def test_a_thumb_inside_the_window_is_kept(self, outcome_store: Any) -> None:
        """The other half: a window that excluded everything would also pass above."""
        await outcome_store.record(_thumb("up", age_days=THUMB_WINDOW_DAYS - 1))

        assert len(await outcome_store.list_thumbs(dag_id="d1")) == 1

    @pytest.mark.ac("SPEC-083026-a1f7/AC-5")
    async def test_the_limit_keeps_the_most_recent(self, outcome_store: Any) -> None:
        """If the bound ever binds, it must drop the oldest, not an arbitrary half."""
        await outcome_store.record(_thumb("down", age_days=5))
        await outcome_store.record(_thumb("up", age_days=0))

        found = await outcome_store.list_thumbs(dag_id="d1", limit=1)

        assert [o.thumb for o in found] == ["up"]

    @pytest.mark.ac("SPEC-083026-a1f7/AC-5")
    async def test_another_orgs_thumb_is_not_returned(self, outcome_store: Any) -> None:
        """Scope authorization, which `list_thumbs` must apply like its siblings."""
        await outcome_store.record(_thumb("up", org_id="org-a"))

        assert await outcome_store.list_thumbs(dag_id="d1", org_id="org-b") == []

    @pytest.mark.ac("SPEC-083026-a1f7/AC-5")
    async def test_naming_no_org_sees_every_org(self, outcome_store: Any) -> None:
        """Empty means unscoped, matching every other read on this protocol."""
        await outcome_store.record(_thumb("up", org_id="org-a"))

        assert len(await outcome_store.list_thumbs(dag_id="d1")) == 1


class TestTheDurableStoresKeepWhatTheyAreGiven:
    """The SQLite twin could not hold a thumb at all before this change.

    Its `outcomes` table stopped at `created_at`: no `thumb`, no `dag_id`, no
    `node_id`, no `org_id`, no `project_id`. `record()` therefore accepted a
    thumb, returned an id for it, and wrote a row with the feedback removed.
    PostgreSQL got those columns in migrations 006 and 010; the twin got
    neither.
    """

    @pytest.mark.ac("SPEC-083026-a1f7/AC-3")
    async def test_every_attribution_field_round_trips(self, outcome_store: Any) -> None:
        await outcome_store.record(
            Outcome(
                task_type="dag_run",
                success=True,
                user_id="u1",
                org_id="org-a",
                project_id="proj-a",
                dag_id="d1",
                dag_run_id="run-7",
                node_id="n2",
                thumb="down",
                thumb_comment="wrong tone",
                eval_judge_score=41.5,
            )
        )

        (found,) = await outcome_store.list_thumbs(dag_id="d1")

        assert (
            found.org_id,
            found.project_id,
            found.dag_id,
            found.dag_run_id,
            found.node_id,
            found.thumb,
            found.thumb_comment,
            found.eval_judge_score,
        ) == ("org-a", "proj-a", "d1", "run-7", "n2", "down", "wrong tone", 41.5)


class TestASqliteFileMadeBeforeTheColumnsExisted:
    """`ensure_schema` upgrades in place rather than requiring a new file.

    A homelab deployment already has an `outcomes` table without these columns.
    Creating the table with `IF NOT EXISTS` would leave it exactly as it was,
    so the added columns need an explicit `ALTER`.
    """

    @pytest.mark.ac("SPEC-083026-a1f7/AC-3")
    async def test_the_old_table_gains_the_columns_and_keeps_its_rows(self) -> None:
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await aiosqlite.connect(":memory:")
        try:
            await conn.execute(
                "CREATE TABLE outcomes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "request_id TEXT NOT NULL DEFAULT '',"
                "task_type TEXT NOT NULL DEFAULT '',"
                "model_used TEXT NOT NULL DEFAULT '',"
                "provider TEXT NOT NULL DEFAULT '',"
                "tool_calls TEXT NOT NULL DEFAULT '',"
                "success INTEGER NOT NULL DEFAULT 1,"
                "error_type TEXT NOT NULL DEFAULT '',"
                "response_time_ms INTEGER NOT NULL DEFAULT 0,"
                "team_id TEXT NOT NULL DEFAULT '',"
                "user_id TEXT NOT NULL DEFAULT '',"
                "agent_id TEXT NOT NULL DEFAULT '',"
                "input_tokens INTEGER NOT NULL DEFAULT 0,"
                "output_tokens INTEGER NOT NULL DEFAULT 0,"
                "charged_microchips INTEGER NOT NULL DEFAULT 0,"
                "pricing_version TEXT NOT NULL DEFAULT '',"
                "created_at TEXT NOT NULL)"
            )
            await conn.execute(
                "INSERT INTO outcomes (task_type, created_at) VALUES ('legacy', ?)",
                (datetime.now(UTC).isoformat(),),
            )
            await conn.commit()

            store = SqliteOutcomeStore(conn)
            await store.ensure_schema()
            await store.record(_thumb("up"))

            assert [o.thumb for o in await store.list_thumbs(dag_id="d1")] == ["up"]
            existing = await store.list_outcomes(task_type="legacy")
            assert [o.task_type for o in existing] == ["legacy"]
        finally:
            await conn.close()
