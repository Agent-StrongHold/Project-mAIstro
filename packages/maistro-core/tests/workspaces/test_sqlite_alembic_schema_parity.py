"""SQLite scope stores and the Alembic head describe the same tables (#1135).

The durable Workspace/Project scope stores ship twice. PostgreSQL deployments
get their tables from the Alembic chain (012, 019, 033); SQLite deployments get
them from each store's own ``CREATE TABLE`` DDL. The two were written to agree
and then drifted apart by editing one side only -- exactly the failure the
Workspace cutover plan calls "SQLite/Alembic schema parity" (§7.3, #1135):
behavioral conformance across backends cannot catch it, because conformance
exercises the stores through their own schemas on both sides.

So this compares the two implementations the way
``tests/migrations/test_event_schema_agreement.py`` compares the event stores'
two DDL sources: against a real catalogue, not against the DDL text. Each side
is read from what it actually creates -- SQLite's ``PRAGMA`` catalogue for the
stores' own ``ensure_schema()``, PostgreSQL's catalogues for a database
migrated to the Alembic head -- and both are held to one dialect-neutral spec:
column sets, nullability, primary keys, foreign keys with their ON DELETE
actions, unique and partial indexes (the one-root-per-Workspace and
owner-roster predicates), and the boolean guard SQLite expresses as a CHECK
where PostgreSQL has a real ``boolean``. A column that appears on one side
only, a nullability flip, a demoted key, or a lost partial index fails here
instead of surfacing as divergent durability between homelab and cloud.

The PostgreSQL leg needs a real migrated server and skips without one, and a
skipped leg is untested rather than passing: ``MAISTRO_REQUIRE_PG_LEGS`` turns
that skip into a failure in the CI job that owns a migrated server.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import aiosqlite
import pytest

from maistro.testing.postgres import postgres_dsn

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The Workspace/Project scope tables whose SQLite implementations claim
#: conformance with an Alembic-managed canonical store. Spelled out rather
#: than derived from either catalogue: a comparison of "the tables that exist"
#: passes vacuously when neither side creates anything.
SCOPE_TABLES = (
    "canonical_workspaces",
    "canonical_workspace_memberships",
    "canonical_projects",
    "canonical_project_memberships",
    "canonical_project_resources",
)

#: The canonical Goal tables (#1572). The same dual-ship applies: SQLite
#: deployments get the Goal store's own DDL (`goals/sqlite_store.py`),
#: PostgreSQL deployments get migration 055 — and the two must not drift.
GOAL_TABLES = (
    "canonical_goals",
    "canonical_goal_revisions",
    "canonical_goal_transitions",
)

PG_TIMESTAMPTZ = frozenset({"timestamp with time zone"})
PG_DOC = frozenset({"jsonb", "json"})
PG_TEXT = frozenset({"text", "character varying", "uuid"})
SQLITE_TEXT = frozenset({"TEXT"})


@dataclass(frozen=True)
class ColumnSpec:
    #: ``None``-acceptance as the Alembic head declares it. Primary-key
    #: columns are non-null in both dialects whether or not the DDL says so.
    nullable: bool
    #: Acceptable catalogue types per dialect. The document columns are
    #: ``JSONB`` on PostgreSQL and ``TEXT`` on SQLite by design; a drift into
    #: anything else on either side is what this check exists to catch.
    pg_types: frozenset[str] = PG_TEXT
    sqlite_types: frozenset[str] = SQLITE_TEXT
    #: SQLite has no ``boolean``; ``is_root`` is an ``INTEGER`` whose CHECK
    #: confines it to two states. PostgreSQL carries the real type. The guard
    #: is the materially relevant constraint, so it is asserted on the side
    #: that can express it.
    sqlite_bool_guard: bool = False


@dataclass(frozen=True)
class TableSpec:
    columns: dict[str, ColumnSpec]
    primary_key: tuple[str, ...]
    #: ``(column, parent_table, parent_column, on_delete)`` with SQLite's
    #: ``on_delete`` spelling normalized to pg_constraint's codes
    #: (``c``ascade, ``r``estrict, ``a`` no action).
    foreign_keys: tuple[tuple[str, str, str, str], ...] = ()
    #: Unique indexes as ``(columns, normalized partial predicate)``; the
    #: empty predicate is a whole-table unique index.
    unique_indexes: frozenset[tuple[tuple[str, ...], str]] = frozenset()
    #: Plain (non-unique) indexes as ``(columns, normalized predicate)``.
    indexes: frozenset[tuple[tuple[str, ...], str]] = frozenset()


def _norm_predicate(sql: str | None) -> str:
    """Normalize a partial-index predicate across dialect spellings.

    SQLite writes the one-root predicate as ``is_root = 1`` where PostgreSQL
    writes ``is_root`` (or ``(is_root)``); both mean the boolean is true.
    Everything else is lowercased and squeezed so cosmetic spacing cannot
    mask -- or fake -- agreement.
    """
    if sql is None:
        return ""
    text = re.sub(r"\s+", " ", sql.strip().strip("()").lower())
    # PostgreSQL annotates literal casts (`'owner'::text`) where SQLite spells
    # the bare literal.
    text = re.sub(r"::[a-z_]+", "", text)
    # Canonical boolean predicate spelling is the bare column: SQLite writes
    # ``is_root = 1``, PostgreSQL's pg_get_expr writes ``is_root`` (or
    # ``(is_root)``); all of them mean the boolean is true.
    text = re.sub(r"is_root\s*=\s*(?:1|true)", "is_root", text)
    return text.replace(" ", "")


@dataclass(frozen=True)
class ActualTable:
    columns: dict[str, tuple[bool, str]] = field(default_factory=dict)  # name -> (nullable, type)
    primary_key: tuple[str, ...] = ()
    foreign_keys: frozenset[tuple[str, str, str, str]] = frozenset()
    unique_indexes: frozenset[tuple[tuple[str, ...], str]] = frozenset()
    indexes: frozenset[tuple[tuple[str, ...], str]] = frozenset()
    check_sql: str = ""


def _spec() -> dict[str, TableSpec]:
    return {
        "canonical_workspaces": TableSpec(
            columns={
                "workspace_id": ColumnSpec(nullable=False),
                "name": ColumnSpec(nullable=False),
                "created_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "updated_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("workspace_id",),
            indexes=frozenset({(("created_at",), "")}),
        ),
        "canonical_workspace_memberships": TableSpec(
            columns={
                "workspace_id": ColumnSpec(nullable=False),
                "user_id": ColumnSpec(nullable=False),
                "role": ColumnSpec(nullable=False),
                "added_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("workspace_id", "user_id"),
            foreign_keys=(("workspace_id", "canonical_workspaces", "workspace_id", "c"),),
            indexes=frozenset(
                {
                    (("user_id",), ""),
                    # "Does this Workspace still have an owner" without
                    # walking the whole roster (019).
                    (("workspace_id",), "role='owner'"),
                }
            ),
        ),
        "canonical_projects": TableSpec(
            columns={
                "project_id": ColumnSpec(nullable=False),
                "workspace_id": ColumnSpec(nullable=False),
                "parent_project_id": ColumnSpec(nullable=True),
                # PostgreSQL: real boolean. SQLite: INTEGER + the CHECK guard.
                "is_root": ColumnSpec(
                    nullable=False,
                    pg_types=frozenset({"boolean"}),
                    sqlite_types=frozenset({"INTEGER"}),
                    sqlite_bool_guard=True,
                ),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("project_id",),
            foreign_keys=(("parent_project_id", "canonical_projects", "project_id", "r"),),
            # One Root Project per Workspace, enforced by the database (012):
            # two concurrent create_root calls cannot both win. The predicate
            # is spelled in the canonical bare-column form `_norm_predicate`
            # reduces both dialects to.
            unique_indexes=frozenset({(("workspace_id",), "is_root")}),
            indexes=frozenset({(("parent_project_id",), ""), (("workspace_id",), "")}),
        ),
        "canonical_project_memberships": TableSpec(
            columns={
                # Stable identity, kept across re-grants -- but not the
                # uniqueness boundary since 033.
                "membership_id": ColumnSpec(nullable=False),
                "workspace_id": ColumnSpec(nullable=False),
                "project_id": ColumnSpec(nullable=False),
                "principal_id": ColumnSpec(nullable=False),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("project_id", "principal_id"),
            foreign_keys=(("project_id", "canonical_projects", "project_id", "r"),),
            indexes=frozenset({(("principal_id",), "")}),
        ),
        "canonical_project_resources": TableSpec(
            columns={
                "resource_id": ColumnSpec(nullable=False),
                "workspace_id": ColumnSpec(nullable=False),
                "project_id": ColumnSpec(nullable=False),
                "resource_type": ColumnSpec(nullable=False),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("resource_id",),
            foreign_keys=(("project_id", "canonical_projects", "project_id", "r"),),
            indexes=frozenset({(("project_id", "resource_type"), "")}),
        ),
        # The canonical Goal store's tables (#1572, migration 055). The
        # compare-and-set pointer is a real column on both sides: the guarded
        # UPDATE is the one cross-process CAS the PG store has, so it can not
        # live only in the payload.
        "canonical_goals": TableSpec(
            columns={
                "goal_id": ColumnSpec(nullable=False),
                "workspace_id": ColumnSpec(nullable=False),
                "project_id": ColumnSpec(nullable=False),
                "agent_id": ColumnSpec(nullable=False),
                "parent_goal_id": ColumnSpec(nullable=True),
                "status": ColumnSpec(nullable=False),
                "current_revision": ColumnSpec(
                    nullable=False,
                    pg_types=frozenset({"integer"}),
                    sqlite_types=frozenset({"INTEGER"}),
                ),
                "created_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "updated_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("goal_id",),
            foreign_keys=(("parent_goal_id", "canonical_goals", "goal_id", "c"),),
            indexes=frozenset({(("project_id",), "")}),
        ),
        "canonical_goal_revisions": TableSpec(
            columns={
                "goal_id": ColumnSpec(nullable=False),
                "revision": ColumnSpec(
                    nullable=False,
                    pg_types=frozenset({"integer"}),
                    sqlite_types=frozenset({"INTEGER"}),
                ),
                "created_at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("goal_id", "revision"),
            foreign_keys=(("goal_id", "canonical_goals", "goal_id", "c"),),
        ),
        "canonical_goal_transitions": TableSpec(
            columns={
                "goal_id": ColumnSpec(nullable=False),
                "seq": ColumnSpec(
                    nullable=False,
                    pg_types=frozenset({"integer"}),
                    sqlite_types=frozenset({"INTEGER"}),
                ),
                "at": ColumnSpec(nullable=False, pg_types=PG_TIMESTAMPTZ),
                "kind": ColumnSpec(nullable=False),
                "payload": ColumnSpec(nullable=False, pg_types=PG_DOC),
            },
            primary_key=("goal_id", "seq"),
            foreign_keys=(("goal_id", "canonical_goals", "goal_id", "c"),),
        ),
    }


async def _sqlite_actual(conn: aiosqlite.Connection) -> dict[str, ActualTable]:
    actual: dict[str, ActualTable] = {}
    for table in (*SCOPE_TABLES, *GOAL_TABLES):
        pk_cols: list[tuple[int, str]] = []
        columns: dict[str, tuple[bool, str]] = {}
        async with conn.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
        assert rows, f"SQLite side created no {table!r} table"
        for _cid, name, decl_type, notnull, _default, pk_ordinal in rows:
            if pk_ordinal:
                pk_cols.append((pk_ordinal, name))
            # Primary-key columns are non-null in SQLite whether or not the
            # DDL says NOT NULL; report real nullability, not the spelling.
            columns[name] = (not (notnull or pk_ordinal), (decl_type or "").upper())
        pk = tuple(name for _, name in sorted(pk_cols))

        indexes: set[tuple[tuple[str, ...], str]] = set()
        unique: set[tuple[tuple[str, ...], str]] = set()
        async with conn.execute(f"PRAGMA index_list({table})") as cur:
            index_rows = await cur.fetchall()
        for row in index_rows:
            # origin: 'c' = CREATE INDEX, 'u' = UNIQUE constraint, 'pk' = the
            # primary key. Only 'c' is this DDL's own statement; the rest are
            # SQLite's automatic shadows of constraints compared above.
            name, uniq, origin = row[1], row[2], row[3]
            if origin != "c":
                continue
            async with conn.execute(f"PRAGMA index_info({name})") as cur:
                cols = tuple(r[2] for r in await cur.fetchall())
            (unique if uniq else indexes).add((cols, ""))

        # Partial-index predicates live in the CREATE INDEX text.
        async with conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
        ) as cur:
            ddl_rows = await cur.fetchall()
        for name, sql in ddl_rows:
            if not sql:
                continue  # automatic shadows (e.g. sqlite_autoindex) carry no DDL text
            is_unique = "CREATE UNIQUE INDEX" in sql.upper()
            match = re.search(r"\bWHERE\s+(.+)$", sql, re.IGNORECASE | re.DOTALL)
            predicate = _norm_predicate(match.group(1)) if match else ""
            async with conn.execute(f"PRAGMA index_info({name})") as cur:
                cols = tuple(r[2] for r in await cur.fetchall())
            # The PRAGMA pass recorded this index with an empty predicate;
            # re-record it with the partial predicate its own DDL declares.
            entry = unique if is_unique else indexes
            entry.discard((cols, ""))
            entry.add((cols, predicate))

        fks: set[tuple[str, str, str, str]] = set()
        async with conn.execute(f"PRAGMA foreign_key_list({table})") as cur:
            for row in await cur.fetchall():
                _fid, _seq, parent, from_col, to_col, _on_update, on_delete = row[:7]
                action = {"CASCADE": "c", "RESTRICT": "r"}.get(str(on_delete).upper(), "a")
                fks.add((from_col, str(parent), str(to_col), action))

        check_sql = ""
        async with conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ) as cur:
            row = await cur.fetchone()
        if row and row[0]:
            check_sql = str(row[0])

        actual[table] = ActualTable(
            columns=columns,
            primary_key=pk,
            foreign_keys=frozenset(fks),
            unique_indexes=frozenset(unique),
            indexes=frozenset(indexes),
            check_sql=check_sql,
        )
    return actual


def _pg_action(code: str | bytes | None) -> str:
    # confdeltype is a "char" column; asyncpg hands bpchar back as bytes.
    text = code.decode() if isinstance(code, bytes) else str(code or "")
    return {"c": "c", "r": "r"}.get(text.lower(), "a")


async def _pg_actual(dsn: str) -> dict[str, ActualTable]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        actual: dict[str, ActualTable] = {}
        for table in (*SCOPE_TABLES, *GOAL_TABLES):
            rows = await conn.fetch(
                """
                SELECT column_name, is_nullable, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                table,
            )
            assert rows, (
                f"PostgreSQL migrated to the Alembic head has no {table!r} table; "
                "run `alembic upgrade head` before this comparison"
            )
            columns = {r["column_name"]: (r["is_nullable"] == "YES", r["data_type"]) for r in rows}

            pk_rows = await conn.fetch(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a
                  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = $1::regclass AND i.indisprimary
                ORDER BY a.attnum
                """,
                f"public.{table}",
            )
            pk = tuple(r["attname"] for r in pk_rows)

            index_rows = await conn.fetch(
                """
                SELECT i.indisunique AS uniq,
                       i.indpred IS NOT NULL AS partial,
                       pg_get_expr(i.indpred, i.indrelid) AS predicate,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = i.indrelid AND a.attnum = k.attnum) AS columns
                FROM pg_index i
                WHERE i.indrelid = $1::regclass
                  AND NOT i.indisprimary
                  AND NOT i.indisunique
                """,
                f"public.{table}",
            )
            indexes = {
                (tuple(r["columns"]), _norm_predicate(r["predicate"]) if r["partial"] else "")
                for r in index_rows
            }

            unique_rows = await conn.fetch(
                """
                SELECT i.indpred IS NOT NULL AS partial,
                       pg_get_expr(i.indpred, i.indrelid) AS predicate,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = i.indrelid AND a.attnum = k.attnum) AS columns
                FROM pg_index i
                WHERE i.indrelid = $1::regclass
                  AND i.indisunique
                  AND NOT i.indisprimary
                """,
                f"public.{table}",
            )
            unique = {
                (tuple(r["columns"]), _norm_predicate(r["predicate"]) if r["partial"] else "")
                for r in unique_rows
            }

            fk_rows = await conn.fetch(
                """
                SELECT sa.attname AS from_col,
                       rc.confrelid::regclass::text AS parent,
                       ra.attname AS to_col,
                       rc.confdeltype AS on_delete
                FROM pg_constraint rc
                JOIN pg_attribute sa
                  ON sa.attrelid = rc.conrelid AND sa.attnum = rc.conkey[1]
                JOIN pg_attribute ra
                  ON ra.attrelid = rc.confrelid AND ra.attnum = rc.confkey[1]
                WHERE rc.contype = 'f' AND rc.conrelid = $1::regclass
                """,
                f"public.{table}",
            )
            fks = {
                (r["from_col"], r["parent"].split(".")[-1], r["to_col"], _pg_action(r["on_delete"]))
                for r in fk_rows
            }

            actual[table] = ActualTable(
                columns=columns,
                primary_key=pk,
                foreign_keys=frozenset(fks),
                unique_indexes=frozenset(unique),
                indexes=frozenset(indexes),
            )
        return actual
    finally:
        await conn.close()


def _compare(
    side: str, is_pg: bool, actual: dict[str, ActualTable], spec: dict[str, TableSpec]
) -> None:
    for table, table_spec in spec.items():
        real = actual[table]
        # Columns: nothing missing, nothing extra, each the declared shape.
        expected_cols = set(table_spec.columns)
        assert set(real.columns) == expected_cols, (
            f"{side} {table}: column set drifted: "
            f"missing={sorted(expected_cols - set(real.columns))} "
            f"extra={sorted(set(real.columns) - expected_cols)}"
        )
        for name, col in table_spec.columns.items():
            nullable, declared = real.columns[name]
            assert nullable == col.nullable, (
                f"{side} {table}.{name}: nullability is {nullable}, spec says {col.nullable}"
            )
            types = col.pg_types if is_pg else col.sqlite_types
            assert declared.lower() in {t.lower() for t in types}, (
                f"{side} {table}.{name}: type {declared!r} outside {sorted(types)}"
            )
            if col.sqlite_bool_guard and not is_pg:
                assert re.search(
                    r"is_root\s+IN\s*\(\s*0\s*,\s*1\s*\)", real.check_sql, re.IGNORECASE
                ), f"{side} {table}: lost the two-state CHECK guard on is_root"

        # Keys.
        assert real.primary_key == table_spec.primary_key, (
            f"{side} {table}: primary key {real.primary_key} != {table_spec.primary_key} "
            "(033 moved Project membership uniqueness to (project_id, principal_id); "
            "a drift back to a membership_id key resurrects the duplicate-grant bug)"
        )
        assert real.foreign_keys == frozenset(table_spec.foreign_keys), (
            f"{side} {table}: foreign keys {sorted(real.foreign_keys)} "
            f"!= {sorted(table_spec.foreign_keys)}"
        )

        # Indexes, unique and plain, partial predicates normalized.
        assert real.unique_indexes == table_spec.unique_indexes, (
            f"{side} {table}: unique indexes {sorted(real.unique_indexes)} "
            f"!= {sorted(table_spec.unique_indexes)}"
        )
        assert real.indexes == table_spec.indexes, (
            f"{side} {table}: indexes {sorted(real.indexes)} != {sorted(table_spec.indexes)}"
        )


@pytest.fixture(params=["sqlite", "postgres"])
def side(request: pytest.FixtureRequest) -> str:
    return request.param


async def test_sqlite_alembic_schema_parity(side: str) -> None:
    """Both implementations of the scope tables match one dialect-neutral spec."""
    spec = _spec()

    if side == "sqlite":
        conn = await aiosqlite.connect(":memory:")
        try:
            from maistro.goals.sqlite_store import SqliteGoalStore
            from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
            from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

            project_store = SqliteProjectScopeStore(conn)
            workspace_store = SqliteWorkspaceStore(conn, project_store=project_store)
            await project_store.ensure_schema()
            await workspace_store.ensure_schema()
            await SqliteGoalStore(conn).ensure_schema()
            _compare("SQLite", False, await _sqlite_actual(conn), spec)
        finally:
            await conn.close()
        return

    dsn = postgres_dsn() or DATABASE_URL
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError(
                "MAISTRO_REQUIRE_PG_LEGS is set but no PostgreSQL DSN is configured: "
                "the SQLite/Alembic parity comparison cannot run and must not be "
                "silently skipped"
            )
        pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; parity needs a migrated server")
    _compare("PostgreSQL", True, await _pg_actual(dsn), spec)
