"""The Run store's retention, archive and queue-cursor queries must stay
planner-stable: index-served under custom *and* generic prepared plans, at
representative cardinality (#863).

Three measured shapes shared one root cause. PostgreSQL switches a prepared
statement to a **generic** plan (parameters as holes, not values) once it looks
cheaper — the steady state of every long-lived sweeper and ticker, which run
far more than five times. A partial index's predicate can only be proven from a
query clause that names the *same constants*; a clause like
`status = ANY($2::text[])` proves nothing in a generic plan, so the sweep that
used the index on its first five executions quietly degraded to a sequential
scan of every Run ever kept — exactly once the table was big enough for the
index to matter. And a sort with no supporting index (`ORDER BY
payload->>'created_at'`, the queue cursor) turned fairness into O(every Run)
per tick under any plan mode.

The fix has three parts, each pinned here:

- the sweeps interpolate the terminal statuses as **literals** (store-owned
  constants derived from the model — the same shape `_ACTIVE_ROOT_COUNTS_SQL`
  already used), so the partial predicates 013/017 carry are provable in every
  plan mode;
- the queue cursor reads `ix_canonical_runs_status_created` (migration 053) —
  deliberately **unconditional**, so `status = $1` needs no predicate proof at
  all, and the index's trailing columns carry both the order and the keyset;
- the status domains are CHECK-constrained to the model enums, so a new status
  fails loudly at write time instead of silently escaping every partial-index
  predicate (held shut statically by `test_status_domain_lockstep.py`).

The live half runs the *shipped* SQL — imported from the store modules, not
re-typed — against a scratch database migrated from empty, seeds a
representative distribution (~40k Runs across all nine statuses with retention
and archive deadlines spread the way production's are; ~3k continuations), and
`EXPLAIN`s it under `plan_cache_mode = force_generic_plan` and
`force_custom_plan`. Plan **shapes** are asserted (which index, is there a Sort
node), never cost figures: costs are workstation-relative, shapes are the
planner's decisions. The negative control re-runs the pre-fix parameterized
shape and asserts the retention index is *unreachable* generically — the
regression this issue closed, kept assertable.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRATCH_DB = "maistro_planner_test"

#: The shipped query builders, imported rather than re-typed: a test that
#: re-spells the SQL asserts on a copy, and the copy is what rots.
from maistro.graph.durable_runs.pg_continuation import (  # noqa: E402
    _list_run_ids_by_status_query,
)
from maistro.runs.pg_store import (  # noqa: E402
    _ARCHIVE_CANDIDATES_SQL,
    _PURGE_CANDIDATES_SQL_GLOBAL,
    _PURGE_CANDIDATES_SQL_SCOPED,
    _TERMINAL_RUN_STATUS_VALUES,
    _list_by_status_query,
)

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: Seed distribution. 40k Runs: ~2/9 live statuses for the queue cursor, the
#: rest terminal with retention deadlines (one in sixty *due*, one in sixty
#: nil so they fall to the archive sweep instead, the rest far-future —
#: how a policy-carrying deployment actually looks) and a finished_at age
#: gradient for the archive order. Two anti-join arms are populated: runs that
#: are themselves children, and runs that spawned NodeRuns.
RUN_ROWS = 40_000
CONTINUATION_ROWS = 3_000
TERMINAL_LITERALS = ", ".join(f"'{value}'" for value in _TERMINAL_RUN_STATUS_VALUES)


# --------------------------------------------------------------------------
# The parts that need no server
# --------------------------------------------------------------------------
class TestTheShippedSqlIsLiteralShaped:
    def test_the_sweeps_name_the_terminal_statuses_as_literals(self) -> None:
        """The whole fix: the clause the planner must prove — `status IN (...)`
        — is spelled in constants, not behind a parameter."""
        for sql in (
            _PURGE_CANDIDATES_SQL_GLOBAL,
            _PURGE_CANDIDATES_SQL_SCOPED,
            _ARCHIVE_CANDIDATES_SQL,
        ):
            assert f"status IN ({TERMINAL_LITERALS})" in sql, sql
            assert "ANY($" not in sql, f"a parameterized status set regressed into {sql!r}"

    def test_the_sweeps_keep_caller_input_parameterized(self) -> None:
        """Literal statuses must not become literal anything else: the cutoff,
        workspace and batch size are caller input and stay behind `$n`."""
        assert "$1" in _PURGE_CANDIDATES_SQL_GLOBAL and "$2" in _PURGE_CANDIDATES_SQL_GLOBAL
        assert "$1" in _PURGE_CANDIDATES_SQL_SCOPED and "$3" in _PURGE_CANDIDATES_SQL_SCOPED
        assert "$1" in _ARCHIVE_CANDIDATES_SQL and "$2" in _ARCHIVE_CANDIDATES_SQL
        # and no caller-supplied string is interpolated anywhere else
        for sql in (
            _PURGE_CANDIDATES_SQL_GLOBAL,
            _PURGE_CANDIDATES_SQL_SCOPED,
            _ARCHIVE_CANDIDATES_SQL,
        ):
            for status_value in _TERMINAL_RUN_STATUS_VALUES:
                assert sql.count(f"'{status_value}'") == 1

    def test_the_status_listing_orders_by_the_indexed_expression(self) -> None:
        """The queue cursor's order must be exactly what migration 053's index
        carries — `(status, payload->>'created_at', run_id)` — or the planner
        pays a Sort node the index cannot remove."""
        source = (
            REPO_ROOT / "alembic" / "versions" / "053_run_store_planner_stability.py"
        ).read_text(encoding="utf-8")
        # No partial indexes in this revision at all: an unconditional
        # (status, created_at, run_id) index is provable under every plan mode,
        # which is the property the acceptance criterion names.
        assert "postgresql_where" not in source
        assert "ix_canonical_runs_status_created" in source
        assert "((payload->>'created_at'))" in source

        sql, _params = _list_by_status_query("queued", limit=10, offset=0)
        assert sql.index("status = $1") < sql.index("ORDER BY payload->>'created_at', run_id")
        assert sql.index("ORDER BY payload->>'created_at', run_id") < sql.index("LIMIT")

    def test_the_status_listing_keeps_every_filter_and_the_keyset(self) -> None:
        """The refactor to a module function must not have changed the query:
        every optional filter still lands between the status predicate and the
        order, and the keyset rides the index's trailing columns."""
        sql, params = _list_by_status_query(
            "queued",
            limit=10,
            offset=5,
            project_id="p1",
            workspace_id="w1",
            admission_source="schedule",
            after=("2026-01-01T00:00:00+00:00", "run-9"),
        )
        assert "project_id = $2" in sql and "workspace_id = $3" in sql
        assert "payload->'provenance'->>'admission_source' = $4" in sql
        assert "(payload->>'created_at', run_id) > ($5, $6)" in sql
        assert params == [
            "queued",
            "p1",
            "w1",
            "schedule",
            "2026-01-01T00:00:00+00:00",
            "run-9",
            10,
            5,
        ]

    def test_the_continuation_listing_has_both_literal_shapes(self) -> None:
        bare, bare_params = _list_run_ids_by_status_query("queued", limit=7)
        assert bare.startswith("SELECT run_id FROM graph_continuations WHERE status = $1")
        assert "ORDER BY created_at ASC, run_id ASC LIMIT $2" in bare
        assert bare_params == ["queued", 7]

        scoped, scoped_params = _list_run_ids_by_status_query(
            "queued", project_id="p-a", after=("2026-01-01T00:00:00+00:00", "run-2"), limit=7
        )
        assert "status = $1 AND project_id = $2" in scoped
        assert "(created_at, run_id) > ($3, $4)" in scoped
        assert "IS NULL OR" not in scoped, "the OR shape can never become an index condition"
        assert scoped_params == ["queued", "p-a", "2026-01-01T00:00:00+00:00", "run-2", 7]


# --------------------------------------------------------------------------
# The parts that need a real server
# --------------------------------------------------------------------------
def _require_postgres() -> str:
    if not DATABASE_URL:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise AssertionError(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is not"
            )
        pytest.skip("MAISTRO_TEST_DATABASE_URL is not set")
    return DATABASE_URL


def _alembic_env(url: str) -> dict[str, str]:
    """`DATABASE_URL` pointed at the scratch database — the resolver's first
    rung (#187), and the only variable this suite sets."""
    parts = urlsplit(url)
    return {
        **os.environ,
        "DATABASE_URL": urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl(),
        "DB_HOST": parts.hostname or "127.0.0.1",
        "DB_PORT": str(parts.port or 5432),
        "DB_NAME": SCRATCH_DB,
        "DB_USER": parts.username or "postgres",
        "DB_PASSWORD": parts.password or "",
    }


async def _recreate_scratch_database(url: str) -> None:
    import asyncpg

    admin = await asyncpg.connect(urlsplit(url)._replace(path="/postgres").geturl())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await admin.close()


_STATUS_ARRAY = (
    "ARRAY['created','queued','running','waiting','paused',"
    "'completed','failed','cancelled','timed_out']"
)

_SEED_SQL = f"""
INSERT INTO canonical_projects (project_id, workspace_id, is_root, payload)
VALUES ('p-seed', 'w-seed', TRUE, '{{}}');

INSERT INTO canonical_runs (run_id, workspace_id, project_id, status, payload)
VALUES ('seed-run-parent', 'w-seed', 'p-seed', 'completed',
        jsonb_build_object('created_at', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')));

INSERT INTO canonical_node_runs (node_run_id, run_id, node_id, ordinal, status, payload)
VALUES ('seed-nr-0', 'seed-run-parent', 'n0', 0, 'completed', '{{}}');

INSERT INTO canonical_runs (
    run_id, workspace_id, project_id, parent_run_id, parent_node_run_id,
    status, payload, retention_expires_at, finished_at)
SELECT
    'seed-run-' || g,
    'w-seed',
    'p-seed',
    CASE WHEN g % 97 = 0 THEN 'seed-run-parent' END,
    CASE WHEN g % 89 = 0 THEN 'seed-nr-0' END,
    ({_STATUS_ARRAY})[1 + (g % 9)],
    jsonb_build_object(
        'created_at',
        to_char(now() - (g * interval '1 second'), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    CASE
        WHEN (g % 9) < 5 THEN NULL
        WHEN g % 60 = 0 THEN now() - interval '1 hour'
        WHEN g % 60 = 1 THEN NULL
        ELSE now() + interval '30 days'
    END,
    CASE WHEN (g % 9) >= 5 THEN now() - (g * interval '1 minute') END
FROM generate_series(0, {RUN_ROWS - 1}) g;

INSERT INTO graph_continuations (run_id, status, project_id, created_at, version, continuation)
SELECT
    'seed-cont-' || g,
    (ARRAY['queued','running','waiting','paused'])[1 + (g % 4)],
    CASE WHEN g % 2 = 0 THEN 'p-a' ELSE 'p-b' END,
    now() - (g * interval '1 second'),
    0,
    '{{}}'
FROM generate_series(0, {CONTINUATION_ROWS - 1}) g;

ANALYZE canonical_runs;
ANALYZE canonical_node_runs;
ANALYZE graph_continuations;
"""


def _seed(url: str) -> None:
    import asyncio

    import asyncpg

    async def run() -> None:
        conn = await asyncpg.connect(urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl())
        try:
            await conn.execute(_SEED_SQL)
        finally:
            await conn.close()

    asyncio.run(run())


@pytest.fixture(scope="module")
def migrated_url() -> str:
    """A scratch database with the whole chain applied, from empty, then
    seeded with the representative distribution."""
    url = _require_postgres()
    asyncio.run(_recreate_scratch_database(url))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=_alembic_env(url),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"alembic upgrade head failed with exit {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)
    _seed(url)
    return urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()


def _nodes(plan: list[dict]) -> list[dict]:
    stack = [plan[0]["Plan"]]
    found = []
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(node.get("Plans", []))
    return found


def _index_names(plan: list[dict]) -> set[str]:
    return {node["Index Name"] for node in _nodes(plan) if "Index Name" in node}


def _node_types(plan: list[dict]) -> set[str]:
    return {node["Node Type"] for node in _nodes(plan)}


async def _explain_prepared(pool, name: str, sql: str, exec_args_sql: str, *, generic: bool):
    """PREPARE the shipped SQL, then EXPLAIN EXECUTE it under an explicit plan
    cache mode — the only deterministic way to see both the custom and the
    generic plan a long-lived sweeper will actually cycle through.

    The EXECUTE arguments are spelled as SQL literals (`EXPLAIN EXECUTE`
    takes no bind parameters) — see `_sql_literal`.
    """
    import asyncpg

    assert isinstance(pool, asyncpg.Pool)
    mode = "force_generic_plan" if generic else "force_custom_plan"
    async with pool.acquire() as conn:
        await conn.execute(f"PREPARE {name} AS {sql}")
        try:
            await conn.execute(f"SET plan_cache_mode = {mode}")
            rows = await conn.fetch(f"EXPLAIN (FORMAT JSON) EXECUTE {name} ({exec_args_sql})")
        finally:
            await conn.execute(f"DEALLOCATE {name}")
            await conn.execute("RESET plan_cache_mode")
    return json.loads(rows[0][0])


def _seq_scanned_relations(plan: list[dict]) -> set[str]:
    """Relations read by Seq Scan. The sweep anti-joins two child tables; a
    tiny seed relation may legitimately be seq-scanned — the property #863
    names is which relation the *candidate* scan reads, not whether every
    node in the tree carries an Index Name."""
    return {
        node["Relation Name"]
        for node in _nodes(plan)
        if node["Node Type"] == "Seq Scan" and "Relation Name" in node
    }


def _scanned_with_index(plan: list[dict]) -> set[str]:
    return {
        node["Relation Name"]
        for node in _nodes(plan)
        if node["Node Type"].startswith("Index") and "Relation Name" in node
    }


class TestPlansAtScale:
    """Plan shapes of the shipped queries at seeded cardinality, under both
    plan-cache modes. Index *names* and node *types*, never costs."""

    @pytest.mark.parametrize("generic", [False, True], ids=["custom", "generic"])
    async def test_retention_sweep_is_index_served_without_a_scan(
        self, migrated_url, generic
    ) -> None:
        import asyncpg

        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool,
                "s863_purge_global",
                _PURGE_CANDIDATES_SQL_GLOBAL,
                f"{_sql_literal(_past_cutoff())}::timestamptz, 201",
                generic=generic,
            )
            assert "ix_canonical_runs_retention" in _index_names(plan)
            assert "ix_canonical_runs_parent_node" in _index_names(plan)
            assert "canonical_runs" not in _seq_scanned_relations(plan)
        finally:
            await pool.close()

    async def test_the_parameterized_shape_this_replaced_cannot_go_generic(
        self, migrated_url
    ) -> None:
        """The negative control. The pre-fix clause — `status = ANY($2)` —
        cannot prove the partial predicate when the value is a hole, which is
        precisely why the literals exist. If this ever starts using the index
        generically, the literal interpolation has become redundant and can be
        revisited; if the *positive* cases above fail, this is the shape they
        regressed to."""
        import asyncpg

        old_shape = _PURGE_CANDIDATES_SQL_GLOBAL.replace(
            f"status IN ({TERMINAL_LITERALS})", "status = ANY($2::text[])"
        )
        # renumber: the literal shape's remaining params are $1, $2; the old
        # shape had cutoff=$1, statuses=$2, limit=$3.
        old_shape = old_shape.replace("LIMIT $2", "LIMIT $3")
        statuses = (
            "ARRAY["
            + ", ".join(_sql_literal(value) for value in _TERMINAL_RUN_STATUS_VALUES)
            + "]::text[]"
        )
        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool,
                "s863_purge_old",
                old_shape,
                f"{_sql_literal(_past_cutoff())}::timestamptz, {statuses}, 201",
                generic=True,
            )
            assert "ix_canonical_runs_retention" not in _index_names(plan)
            assert "canonical_runs" in _seq_scanned_relations(plan)
        finally:
            await pool.close()

    @pytest.mark.parametrize("generic", [False, True], ids=["custom", "generic"])
    async def test_archive_sweep_is_index_served(self, migrated_url, generic) -> None:
        import asyncpg

        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool,
                "s863_archive",
                _ARCHIVE_CANDIDATES_SQL,
                f"{_sql_literal(_past_cutoff())}::timestamptz, 201",
                generic=generic,
            )
            assert "ix_canonical_runs_archive_candidates" in _index_names(plan)
            assert "canonical_runs" not in _seq_scanned_relations(plan)
        finally:
            await pool.close()

    @pytest.mark.parametrize("generic", [False, True], ids=["custom", "generic"])
    async def test_queue_cursor_needs_no_sort(self, migrated_url, generic) -> None:
        """The starvation cursor: a page of one status in created_at order.
        The unconditional (status, created_at, run_id) index provides both the
        filter and the order — under a generic plan, where no partial status
        index could be proven at all."""
        import asyncpg

        sql, _params = _list_by_status_query("queued", limit=100, offset=0)
        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool,
                "s863_list_status",
                sql,
                "'queued'::text, 100::bigint, 0::bigint",
                generic=generic,
            )
            assert "ix_canonical_runs_status_created" in _index_names(plan)
            assert "Sort" not in _node_types(plan)
            assert "Seq Scan" not in _node_types(plan)
        finally:
            await pool.close()

    @pytest.mark.parametrize("project", [None, "p-a"], ids=["workspace_wide", "per_project"])
    @pytest.mark.parametrize("generic", [False, True], ids=["custom", "generic"])
    async def test_continuation_cursor_needs_no_sort(self, migrated_url, project, generic) -> None:
        import asyncpg

        sql, _params = _list_run_ids_by_status_query("queued", project_id=project, limit=100)
        exec_args = "'queued'::text" if project is None else "'queued'::text, 'p-a'::text"
        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool,
                "s863_cont",
                sql,
                f"{exec_args}, 100::bigint",
                generic=generic,
            )
            assert "ix_graph_continuations_status_created" in _index_names(plan)
            assert "Sort" not in _node_types(plan)
            assert "Seq Scan" not in _node_types(plan)
        finally:
            await pool.close()

    async def test_the_parent_anti_join_probe_uses_the_new_index(self, migrated_url) -> None:
        """Every purge candidate probes `parent_node_run_id` twice (children of
        the run, children of its node runs), and every NodeRun delete re-probes
        it for the RESTRICT foreign key. The probe is generic by construction —
        it runs inside a plan whose outer statement was prepared long ago."""
        import asyncpg

        probe = "SELECT 1 FROM canonical_runs c2 WHERE c2.parent_node_run_id = $1 LIMIT 1"
        pool = await asyncpg.create_pool(migrated_url, min_size=1)
        try:
            plan = await _explain_prepared(
                pool, "s863_probe", probe, "'seed-run-x'::text", generic=True
            )
            assert "ix_canonical_runs_parent_node" in _index_names(plan)
        finally:
            await pool.close()


def _sql_literal(value: str) -> str:
    """A quoted SQL literal — `EXPLAIN EXECUTE` takes no bind parameters."""
    return "'" + value.replace("'", "''") + "'"


def _past_cutoff() -> str:
    """An ISO cutoff the seed's due deadlines (`now() - 1 hour`) fall behind."""
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(minutes=30)).isoformat()


class TestStatusDomainsAreDatabaseConstrained:
    async def test_a_status_outside_the_model_cannot_be_written(self, migrated_url) -> None:
        """The loud failure the CHECK constraints buy: a new status cannot
        silently escape the partial-index predicates, because it cannot be
        written at all until a migration extends the domain."""
        import asyncpg

        refused = [
            (
                "INSERT INTO canonical_runs"
                " (run_id, workspace_id, project_id, status, payload)"
                " VALUES ('ck-fail', 'w-seed', 'p-seed', $1, '{}')",
                "dreaming",
                "canonical_runs",
            ),
            (
                "INSERT INTO canonical_node_runs"
                " (node_run_id, run_id, node_id, ordinal, status, payload)"
                " VALUES ('ck-fail', 'seed-run-parent', 'n0', 98, $1, '{}')",
                "dreaming",
                "canonical_node_runs",
            ),
            (
                # Run domain on purpose: a *valid Run status* must not satisfy
                # the Attempt constraint — the two domains are not
                # interchangeable, and 'queued' proves the refusal is the
                # domain's, not the value's.
                "INSERT INTO canonical_attempts"
                " (attempt_id, node_run_id, ordinal, status, payload)"
                " VALUES ('ck-fail', 'seed-nr-0', 98, $1, '{}')",
                "queued",
                "canonical_attempts",
            ),
            (
                "INSERT INTO graph_continuations"
                " (run_id, status, project_id, version, continuation)"
                " VALUES ('ck-fail', $1, 'p-seed', 0, '{}')",
                "dreaming",
                "graph_continuations",
            ),
        ]
        conn = await asyncpg.connect(migrated_url)
        try:
            for sql, status, _table in refused:
                with pytest.raises(asyncpg.exceptions.CheckViolationError):
                    await conn.execute(sql, status)
        finally:
            await conn.close()

    async def test_every_model_status_is_writable(self, migrated_url) -> None:
        """The degenerate direction: the constraint must not be *tighter* than
        the model, or a legitimate status becomes unwritable at the spine."""
        import asyncpg

        from maistro.runs.model import AttemptStatus, RunStatus

        conn = await asyncpg.connect(migrated_url)
        try:
            for i, status in enumerate(RunStatus):
                run_id = f"ck-ok-run-{i}"
                await conn.execute(
                    "INSERT INTO canonical_runs (run_id, workspace_id, project_id, status, payload)"
                    " VALUES ($1, 'w-seed', 'p-seed', $2, '{}')",
                    run_id,
                    status.value,
                )
                await conn.execute("DELETE FROM canonical_runs WHERE run_id = $1", run_id)
            for i, status in enumerate(AttemptStatus):
                attempt_id = f"ck-ok-att-{i}"
                await conn.execute(
                    "INSERT INTO canonical_attempts (attempt_id, node_run_id, ordinal, status, payload)"
                    " VALUES ($1, 'seed-nr-0', $2, $3, '{}')",
                    attempt_id,
                    100 + i,
                    status.value,
                )
                await conn.execute(
                    "DELETE FROM canonical_attempts WHERE attempt_id = $1", attempt_id
                )
        finally:
            await conn.close()


class TestTheRevisionShapedTheCatalog:
    async def test_053s_indexes_exist_and_the_redundant_one_is_gone(self, migrated_url) -> None:
        """The write-cost side of the acceptance: 053 adds exactly its three
        indexes and *drops* `ix_graph_continuations_status` — (status,
        project_id) — whose filter the status listing never used as an order
        and whose job the new index subsumes. One index on the table, not two."""
        import asyncpg

        conn = await asyncpg.connect(migrated_url)
        try:
            rows = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes"
                " WHERE tablename IN ('canonical_runs', 'graph_continuations')"
                " AND indexname LIKE 'ix_%'"
            )
            by_name = {row["indexname"]: row["indexdef"] for row in rows}
            assert "ix_canonical_runs_parent_node" in by_name
            assert "ix_canonical_runs_status_created" in by_name
            assert "ix_graph_continuations_status_created" in by_name
            assert "ix_graph_continuations_status" not in by_name, (
                "the replaced (status, project_id) index must be dropped, not kept "
                "as write amplification"
            )
            # The queue index is unconditional: no WHERE clause, so a generic
            # plan needs no predicate proof.
            assert " WHERE " not in by_name["ix_canonical_runs_status_created"]
            assert "payload ->> 'created_at'" in by_name["ix_canonical_runs_status_created"]
        finally:
            await conn.close()
