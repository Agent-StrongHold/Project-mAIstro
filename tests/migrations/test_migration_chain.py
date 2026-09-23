"""The alembic chain must apply to an empty PostgreSQL database (#177).

For a long time it could not: migration 003 declared foreign keys to `orgs.id`
and `teams.id`, and because alembic runs the chain under transactional DDL, 003
failing rolled 001 and 002 back with it. A fresh database ended with **zero**
tables, at the first command of every documented Postgres setup path. The fix
that landed created those two scope tables in 003 itself.

That made the chain apply and left the product unable to write: nothing
populated `orgs`, so the only `org_id` the Design Studio supplies failed the
key on every insert (#326). Migration 024 drops both constraints and both
tables — `org` and `team` are soft scope axes (ADR-068), which is what every
other table in this schema already assumed — so `orgs` and `teams` are absent
from `EXPECTED_TABLES` below, and their absence is the assertion.

It went unnoticed because nothing ever ran it: no workflow had a `postgres`
service, and the synchronous driver alembic needs was declared nowhere, so the
chain died with `ModuleNotFoundError` before it could reach the real error. A
migration chain that has never been applied has never been able to fail a
build. This suite is the half that keeps that from recurring — it asserts on
the **live catalog** rather than on the migration source, so it also sees a
future migration that reintroduces the shape.

Needs a real server and skips without one, so `MAISTRO_TEST_DATABASE_URL` is
what makes it run; `ci.yml`'s `postgres` job sets it against the same service
it already applies the chain to. Skipping when it is unset is deliberate — the
alternative is a suite that cannot run on a laptop — but the skip is exactly
what let the original bug survive, so the CI wiring is the part that matters.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

#: Every table the chain is expected to leave behind, `alembic_version` aside.
#: Spelled out rather than counted: a count still passes when one table is
#: dropped and another added, which is precisely the change that wants reading.
EXPECTED_TABLES = frozenset(
    {
        "agents",
        "asset_definitions",
        "asset_instances",
        "asset_sheets",
        "audit_log",
        "books",
        "capability_invocations",
        "consumer_cursors",
        # The canonical execution spine (012) and the template registry it
        # instantiates Runs from (014). Six tables and one, not seven of a
        # kind: `canonical_projects` and its two child tables are the scope a
        # Run is owned by, and they are listed here rather than left implicit
        # because a Run whose Project vanished is the orphan the foreign keys
        # exist to refuse.
        "canonical_attempts",
        "canonical_event_log",
        "canonical_node_runs",
        "canonical_project_memberships",
        "canonical_project_resources",
        "canonical_projects",
        "canonical_runs",
        # The Workspace those Projects and Runs belong to (#516). Their
        # `workspace_id` columns were bare Text with nothing to reference
        # until migration 019 gave the Workspace a table of its own.
        "canonical_workspaces",
        "canonical_workspace_memberships",
        "child_profiles",
        "design_outputs",
        "design_projects",
        "episodic_memories",
        "event_log",
        "graph_continuations",
        "graph_templates",
        "handler_invocations",
        "knowledge_nodes",
        "learnings",
        "memory_entries",
        # The NodeTemplate half of the reusable-definition model (020). Its
        # GraphTemplate sibling has been durable since 014; without this one a
        # Node's `source_template` named a version nothing could resolve after a
        # restart (#556).
        "node_templates",
        "outcomes",
        # A version and the label pointing at it were one row until 022; a
        # version may carry several labels, which that shape had no room for
        # (#328).
        "prompt_labels",
        "prompts",
        "quota_usage",
        # Schedule definitions and their fire cursors (016). Durable so that a
        # cursor survives a restart and two scheduler replicas share one rather
        # than each keeping a private copy (#231).
        "schedules",
        "security_rate_limits",
        "security_strikes",
        "security_violations",
        # A turn's at-most-once marker, a row of its own since 023: one turn
        # writes several messages, so the key that admits a turn once cannot
        # live on the message table (#327).
        "session_turns",
        "sessions",
        # Admission claims for task submission (038, fenced by 039). Durable and
        # replica-shareable
        # so a retried submit resolves to the original receipt rather than minting
        # a second Run (#1176).
        "task_idempotency",
        "tasks",
        "trigger_definitions",
    }
)


def _alembic_env() -> dict[str, str]:
    """alembic/env.py resolves one URL through `require_database_url` (#187)."""
    return {**os.environ, "DATABASE_URL": DATABASE_URL}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    # psycopg 3: the declared synchronous driver. A bare `postgresql://` URL
    # resolves to psycopg2 inside SQLAlchemy, which is why `to_sync_url` names
    # this one explicitly — and why importing it by name here is the honest
    # spelling rather than reaching for whatever happens to be installed.
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return list(cur.fetchall())


def _execute(sql: str, params: tuple[object, ...] = ()) -> None:
    """Run a statement that returns no rows. `_query` always fetches, so an
    INSERT through it raises `the last operation didn't produce records`."""
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]


def _tables() -> set[str]:
    return {
        str(row[0])
        for row in _query("select tablename from pg_tables where schemaname = %s", ("public",))
    }


@pytest.fixture
def empty_database():
    """Start each test from `base`, so one failure cannot cascade into the next."""
    _alembic("downgrade", "base")
    yield
    _alembic("downgrade", "base")


class TestTheChainApplies:
    def test_upgrade_head_succeeds_on_an_empty_database(self, empty_database) -> None:
        """The exact command the README gives, against the state it assumes."""
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr

    def test_upgrade_head_creates_every_expected_table(self, empty_database) -> None:
        """Not merely "did not raise". The original failure left zero tables
        while the process still had to be read to know that."""
        _alembic("upgrade", "head")
        assert _tables() - {"alembic_version"} == EXPECTED_TABLES

    def test_no_migration_references_a_table_the_chain_does_not_create(
        self, empty_database
    ) -> None:
        """The specific defect: a foreign key to a table nothing makes.

        Asserted against the live catalog rather than by reading the migration
        source, so it also covers a reference introduced by a future migration.
        """
        _alembic("upgrade", "head")
        tables = _tables()
        # Without this the test passes vacuously on exactly the bug it is for:
        # the broken chain left zero tables, so there were zero foreign keys and
        # `set() <= set()` held. An empty database must fail here, not pass.
        assert tables >= EXPECTED_TABLES, "the chain did not reach head; nothing to check"

        references = {
            str(row[1])
            for row in _query(
                """
                select conrelid::regclass::text, confrelid::regclass::text
                from pg_constraint
                where contype = 'f' and connamespace = 'public'::regnamespace
                """
            )
        }
        assert references, "no foreign keys at all; this check would prove nothing"
        assert references <= tables, f"foreign keys to absent tables: {references - tables}"

    def test_the_chain_round_trips(self, empty_database) -> None:
        """`downgrade base` then `upgrade head` must reach the same schema.

        A downgrade that does not fully undo its upgrade leaves the next
        migration to land on a shape nobody has tested.
        """
        _alembic("upgrade", "head")
        first = _tables()
        assert _alembic("downgrade", "base").returncode == 0
        assert _tables() - {"alembic_version"} == set()
        assert _alembic("upgrade", "head").returncode == 0
        assert _tables() == first


class TestIndexIntent:
    def test_the_recency_indexes_are_actually_descending(self, empty_database) -> None:
        """`postgresql_order_by=` is not a real argument — SQLAlchemy raises on
        it rather than ignoring it, so this was unreachable behind the foreign
        key error. Read from the catalog, because the point is what the server
        built, not what the migration asked for.
        """
        _alembic("upgrade", "head")
        # Only these two. `ix_outcomes_created_at` (migration 001) is a plain
        # ascending index and never claimed otherwise — sweeping every
        # `%_created_at` index into this assertion tests a decision nobody made.
        descending = ("idx_design_projects_created_at", "idx_design_outputs_created_at")
        definitions = {
            str(name): str(definition)
            for name, definition in _query(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' and indexname = any(%s)",
                (list(descending),),
            )
        }
        assert set(definitions) == set(descending), f"missing: {set(descending) - set(definitions)}"
        for name, definition in definitions.items():
            assert "created_at DESC" in definition, f"{name} is not descending: {definition}"


class TestTheChainSurvivesRuntimeSelfProvisioning:
    """The claims table has two owners (#1176): this chain, and the runtime —
    `PgTaskIdempotencyStore.ensure_schema` provisions the fenced table at wire
    time on a spine-ready pool. The shipped entrypoint applies the chain under
    the migration advisory lock before any replica serves, so a provisioning
    can never race the chain from below; what migration 039 instead meets is
    whatever a hand-managed database has standing under the claims name — the
    migration-038 shape, which it fences in place; a fenced provisioning,
    which it adopts; or a foreign shape, which it refuses loudly rather than
    stamping over."""

    CLAIM_COLUMNS: ClassVar[set[str]] = {
        "scope_key",
        "claim_token",
        "fingerprint",
        "request",
        "task_id",
        "run_id",
        "completed_at",
        "created_at",
        "expires_at",
        "lease_expires_at",
    }

    def _provision_at_runtime(self) -> None:
        """What wiring does on a spine-ready pool below head: the real
        `ensure_schema`, not a re-spelling of its DDL."""

        async def provision() -> None:
            import asyncpg

            from maistro.tasks.idempotency import PgTaskIdempotencyStore

            pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=1)
            try:
                await PgTaskIdempotencyStore(pool).ensure_schema()
            finally:
                await pool.close()

        asyncio.run(provision())

    def _claim_columns(self) -> set[str]:
        return {
            str(row[0])
            for row in _query(
                "select column_name from information_schema.columns "
                "where table_name = 'task_idempotency'"
            )
        }

    def _recreate_the_038_table(self) -> None:
        """Leave behind exactly what migration 038 creates, so the shared
        fixture's `downgrade base` — which replays 038's own downgrade, index
        and table — finds a chain-owned shape after a test dropped it."""
        _execute(
            "create table task_idempotency ("
            "scope_key text not null,"
            "fingerprint text not null,"
            "request text not null,"
            "task_id text,"
            "run_id text,"
            "created_at bigint not null,"
            "expires_at bigint not null,"
            "lease_expires_at bigint not null,"
            "constraint pk_task_idempotency primary key (scope_key)"
            ")"
        )
        _execute("create index ix_task_idempotency_expires on task_idempotency (expires_at)")

    def test_upgrade_evolves_the_migration_038_table_in_place(self, empty_database) -> None:
        """The mainline path: every deployment that walked the chain to 038
        holds the unfenced claims shape, and 039 — not a rewrite of landed
        038 — is what fences it. Rows admitted under 038 survive with
        backfilled fence tokens; their receipts keep replaying."""
        _alembic("upgrade", "038")
        _execute(
            "insert into task_idempotency (scope_key, fingerprint, request, task_id,"
            " run_id, created_at, expires_at, lease_expires_at)"
            " values ('scope-1', 'fp', '{}', 'task-1', 'run-1', 1,"
            " 999999999999999, 1)"
        )
        # The runtime's own provisioning runs against the standing 038 table
        # too (a restart on new code, before migrations caught up): its
        # CREATE TABLE IF NOT EXISTS must no-op rather than clobber or
        # half-fence the shape — 039 is the migration that fences it.
        self._provision_at_runtime()
        assert "claim_token" not in self._claim_columns(), (
            "wire-time provisioning mutated the standing 038 table"
        )

        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        assert self._claim_columns() == self.CLAIM_COLUMNS
        rows = _query("select scope_key, claim_token, completed_at from task_idempotency")
        assert rows == [("scope-1", rows[0][1], 0)], "the admitted row did not survive"
        assert rows[0][1], "the fence token was not backfilled"
        assert _query("select version_num from alembic_version") == [("039",)]

    def test_upgrade_adopts_a_fenced_provisioning_without_a_primary_key(
        self, empty_database
    ) -> None:
        """A wire-time provisioning that predates the PRIMARY KEY in
        ensure_schema leaves a column-complete table with no unique constraint
        — adopting it as-is would stamp head over a shape the store's
        INSERT ... ON CONFLICT cannot write through. The migration must
        reconstruct the PK, or refuse."""
        _alembic("upgrade", "038")
        _execute("drop table task_idempotency")
        # All ten columns, but no PK and no index — the shape an early
        # provisioning leaves standing:
        _execute(
            "create table task_idempotency ("
            "scope_key text not null,"
            "claim_token text not null,"
            "fingerprint text not null,"
            "request text not null,"
            "task_id text,"
            "run_id text,"
            "completed_at bigint not null default 0,"
            "created_at bigint not null,"
            "expires_at bigint not null,"
            "lease_expires_at bigint not null"
            ")"
        )
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        assert _query("select version_num from alembic_version") == [("039",)]
        pks = {
            str(row[0])
            for row in _query(
                "select a.attname from pg_index i "
                "join pg_attribute a on a.attnum = any(i.indkey) and a.attrelid = i.indrelid "
                "where i.indrelid = 'task_idempotency'::regclass and i.indisprimary"
            )
        }
        assert pks == {"scope_key"}, f"primary key missing or wrong: {pks}"
        assert "ix_task_idempotency_expires" in {
            str(row[0])
            for row in _query(
                "select indexname from pg_indexes where tablename = 'task_idempotency'"
            )
        }, "the purge index was not restored"

    def test_upgrade_refuses_to_stamp_over_a_foreign_table_shape(self, empty_database) -> None:
        """A table under the claims name WITHOUT the columns migration 039
        owns is neither the 038 claim table nor the runtime's provisioning,
        and stamping head over a shape the store cannot read would hide the
        damage behind a green upgrade."""
        _alembic("upgrade", "038")
        _execute("drop table task_idempotency")
        _execute("create table task_idempotency (scope_key text primary key)")
        try:
            result = _alembic("upgrade", "head")

            assert result.returncode != 0
            assert "missing" in result.stderr
            assert _query("select version_num from alembic_version") == [("038",)]
            # And the foreign table was left exactly as found — visible, not
            # silently adopted or dropped.
            assert self._claim_columns() == {"scope_key"}
        finally:
            # The refusal leaves the foreign table standing by design; the
            # `empty_database` fixture can only downgrade what the chain owns,
            # so the foreign table is replaced with the shape 038 creates —
            # leaving anything else would poison every later test's `upgrade
            # head` and the fixture's own downgrade exactly the way the
            # refusal just proved it poisons the chain.
            _execute("drop table task_idempotency")
            self._recreate_the_038_table()


class TestADesignProjectIsWritableOnACleanDatabase:
    """The half a schema assertion cannot reach (#326, SPEC-083026-6bc5).

    Every check above asks what the chain built. This one asks whether the
    product can use it, which is where #177's repair stopped: `orgs` and `teams`
    existed, so the tables were all present and the round trip was clean, and an
    ordinary insert still failed the foreign key because nothing ever put a row
    in either.
    """

    #: What `routes/design.py` supplies for the Agent Conductor. Written out
    #: rather than imported: the Conductor's package is not on this suite's path,
    #: and a test that imported the value under test could not have caught a
    #: constraint that rejected every value.
    CONDUCTOR_ORG_ID = "default-org"

    def _insert(self, org_id: str) -> None:
        _execute(
            "insert into design_projects (name, skill_slug, design_system_slug, org_id) "
            "values (%s, %s, %s, %s)",
            ("probe", "login-flow", "default", org_id),
        )

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_the_scope_the_product_supplies_can_be_written(self, empty_database) -> None:
        _alembic("upgrade", "head")
        self._insert(self.CONDUCTOR_ORG_ID)
        assert _query("select count(*) from design_projects")[0][0] == 1

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_a_project_naming_no_scope_is_refused(self, empty_database) -> None:
        """The constraint that replaces the key. It asks whether the caller
        named a scope, which is a question with an answer; the key asked whether
        the scope was a row in a table nothing writes."""
        import psycopg

        _alembic("upgrade", "head")
        with pytest.raises(psycopg.errors.CheckViolation):
            self._insert("")

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_no_table_exists_only_to_be_referenced(self, empty_database) -> None:
        """`orgs` and `teams` held nothing but ids for the foreign keys to
        resolve. Leaving them standing is an invitation for the next migration
        to reference them again."""
        _alembic("upgrade", "head")
        assert {"orgs", "teams"} & _tables() == set()

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_the_round_trip_survives_a_project_with_an_empty_team(self, empty_database) -> None:
        """`team_id` is nullable and unchecked, so `''` and `NULL` both meant
        "no team" — two spellings of one fact. The downgrade has to give every
        non-null `team_id` an anchor row before it can restore the foreign key,
        and `''` is a value no sensible anchor can carry, so one such project
        aborted the rollback (Codex, #326). 024 normalizes it to `NULL`.
        """
        _alembic("upgrade", "head")
        self._insert(self.CONDUCTOR_ORG_ID)
        _execute("update design_projects set team_id = ''")

        assert _alembic("downgrade", "023").returncode == 0
        assert _query("select id from teams") == [], "an empty team is no team"
        assert _alembic("upgrade", "head").returncode == 0
        assert _query("select team_id from design_projects") == [(None,)]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_an_empty_team_is_normalised_on_upgrade(self, empty_database) -> None:
        """Normalized where the rows are written, not only where they are read
        back: a later migration reading `team_id` should not have to know that
        two values mean the same thing."""
        _alembic("upgrade", "023")
        # Before 024 the FK is still in place, so the anchor rows have to exist.
        _execute("insert into orgs (id, name) values (%s, %s)", ("o", "o"))
        _execute("insert into teams (id, org_id, name) values (%s, %s, %s)", ("", "o", ""))
        _execute(
            "insert into design_projects (name, skill_slug, design_system_slug, org_id, team_id) "
            "values (%s, %s, %s, %s, %s)",
            ("probe", "s", "ds", "o", ""),
        )
        assert _alembic("upgrade", "head").returncode == 0
        assert _query("select team_id from design_projects") == [(None,)]

    @pytest.mark.ac("SPEC-083026-6bc5/AC-1")
    def test_the_round_trip_survives_a_row_whose_scope_names_nothing(self, empty_database) -> None:
        """Re-adding a foreign key over such a row aborts, and after 024 every
        row is such a row — so the downgrade has to backfill the anchors before
        it restores the keys. That is why the pre-024 shape was never
        round-trippable with data in it.
        """
        _alembic("upgrade", "head")
        self._insert(self.CONDUCTOR_ORG_ID)
        _execute("update design_projects set team_id = 'team-a'")

        assert _alembic("downgrade", "023").returncode == 0
        assert _query("select id from orgs") == [(self.CONDUCTOR_ORG_ID,)]
        assert _query("select id, org_id from teams") == [("team-a", self.CONDUCTOR_ORG_ID)]

        assert _alembic("upgrade", "head").returncode == 0
        assert _query("select count(*) from design_projects")[0][0] == 1
        assert {"orgs", "teams"} & _tables() == set()
