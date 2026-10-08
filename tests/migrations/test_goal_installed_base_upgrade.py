"""The Goal migration must append after develop's merged identities (#1572).

The installed base already carries two migration identities this branch may
not reuse: develop merged the user-model tables as ``056_user_model_facts``
(#1951's merge ``c560d4c``) and planner stability as
``057_run_store_planner_stability`` (#1914's merge ``4675101``). A database
those trees migrated stands stamped at ``056`` or ``057``. An earlier draft of
this branch numbered the Goal store ``056`` and renumbered the merged
revisions onto ``057``/``058`` — on such a database ``alembic upgrade head``
would then treat the Goal DDL as already applied and silently skip it, leaving
a deployment whose Goals vanish on every restart. The 2026-10-06
clarification on #1572 forbids exactly that: merged identities keep their
meaning and ancestry, and the new revision appends after the integrated
develop head under an unused id. The integrated tree claims ``058`` for
learning-validation provenance and ``059``/``060`` for backlog work-source
and authority cutover; HITL pause-kind projection landed as ``061``.
Goals append as ``062_canonical_goals`` rather than reusing those installed
identities.

So this suite proves the three things the clarification asks for:

* **Identity** — ``056``/``057`` still mean what develop shipped, and the
  Goal revision is a fresh id parented on the integrated head. Read from the
  revision graph, so no server is needed.
* **Provenance** — the restored files are byte-identical to the merged
  snapshots. Needs those commits in the clone; a shallow checkout skips it,
  and the identity test above still pins the graph shape.
* **Installed-base upgrade** — a database migrated by the *actual* develop
  snapshots forward-upgrades to the candidate head with no stamp edit and no
  reset: user-model facts, statement keys and a representative Run survive
  unchanged, the planner's indexes and status constraints are still present,
  the three Goal tables exist, and the durable Goal composition persists and
  reads back Goals, revisions and immutable bound Run provenance on the
  upgraded schema.

The PostgreSQL legs need a real server and skip without one
(``MAISTRO_TEST_DATABASE_URL``); a skipped leg is untested rather than
passing, and CI's ``postgres`` jobs own migrated servers for both supported
majors.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "alembic" / "versions"
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The develop merge commits that shipped the two merged identities, named by
#: the #1572 clarification (2026-10-06). Both carry the file content below as
#: their exact state at merge time (verified against origin/develop's tip).
USER_MODEL_MERGE = "c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250"
PLANNER_MERGE = "4675101647e629d290e0fece29694e43883e1395"
HITL_MERGE = "66f3cea9e98980f146a12cf3142d66e30986d276"
HITL_FILE = "alembic/versions/061_hitl_pause_kind_index.py"
USER_MODEL_FILE = "alembic/versions/056_user_model_facts.py"
PLANNER_FILE = "alembic/versions/057_run_store_planner_stability.py"

#: The single linear head after HITL ``061`` and the Goal store.
GOAL_REVISION = "062"

GOAL_TABLES = ("canonical_goals", "canonical_goal_revisions", "canonical_goal_transitions")
USER_MODEL_TABLES = ("user_model_facts", "user_model_statement_keys")

#: Planner-stability artifacts (057) an installed base must still have after
#: the upgrade — the reason #863 landed at all.
PLANNER_INDEXES = (
    "ix_canonical_runs_status_created",
    "ix_canonical_runs_parent_node",
    "ix_graph_continuations_status_created",
)
PLANNER_CHECK = "ck_canonical_runs_status"

PG_MARK = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)


def _alembic_env() -> dict[str, str]:
    """alembic/env.py resolves one URL through `require_database_url` (#187)."""
    return {**os.environ, "DATABASE_URL": DATABASE_URL}


def _alembic(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=cwd,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return list(cur.fetchall())


def _execute(sql: str, params: tuple[object, ...] = ()) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]


def _tables() -> set[str]:
    return {
        str(row[0]) for row in _query("select tablename from pg_tables where schemaname = 'public'")
    }


def _stamp() -> str:
    return str(_query("select version_num from alembic_version")[0][0])


def _have_commit(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _snapshot_tree(commit: str, dest: Path) -> Path:
    """The actual pre-Goal develop tree's alembic directory, extracted.

    Includes that tree's own ``alembic.ini``, so the upgrade runs with the
    script location and logging the snapshot itself shipped."""
    proc = subprocess.run(
        ["git", "archive", commit, "alembic", "alembic.ini"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=proc.stdout, check=True)
    return dest


def _asyncpg_dsn() -> str:
    """The same database as ``DATABASE_URL``, spelled for asyncpg stores."""
    configured = os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()
    if configured:
        return configured
    from sqlalchemy.engine import make_url

    url = make_url(DATABASE_URL).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


@pytest.fixture
def empty_database():
    """Start each test from `base`, so one failure cannot cascade."""
    _alembic("downgrade", "base")
    for (name,) in _query("select tablename from pg_tables where schemaname = 'public'"):
        quoted = str(name).replace('"', '""')
        _execute(f'drop table if exists "{quoted}" cascade')
    yield
    _alembic("downgrade", "base")
    for (name,) in _query("select tablename from pg_tables where schemaname = 'public'"):
        quoted = str(name).replace('"', '""')
        _execute(f'drop table if exists "{quoted}" cascade')
    # This module is collected inside the shared tests/migrations PostgreSQL
    # run. Its installed-base scenarios must leave that shared database at the
    # same migrated head the following modules expect, not empty after their
    # isolated downgrade walk.
    restored = _alembic("upgrade", "head")
    assert restored.returncode == 0, restored.stderr


def _insert_installed_base_rows(prefix: str) -> None:
    """User-model facts, their statement keys, and a representative Run.

    Written against the snapshot-migrated schema through plain SQL: what
    matters is that these are rows an installed base already had *before*
    the candidate's revisions ran, so the upgrade must leave every value
    exactly as written.
    """
    _execute(
        """
        insert into user_model_facts
            (fact_id, lineage_id, revision, supersedes, owner_user_id, kind,
             statement, evidence, first_observed, last_observed,
             last_reinforced, confidence, state, valid_from, valid_until,
             sensitivity, reusable, correction, persona_hints)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            f"{prefix}-fact-1",
            f"{prefix}-lineage-1",
            2,
            None,
            "owner-installed-base",
            "preference",
            "prefers concise answers",
            '{"source": "installed-base"}',
            "2026-09-01T00:00:00Z",
            "2026-09-02T00:00:00Z",
            "2026-09-03T00:00:00Z",
            0.75,
            "active",
            None,
            None,
            "workspace",
            True,
            None,
            "[]",
        ),
    )
    _execute(
        "insert into user_model_statement_keys (fact_key, lineage_id, owner_user_id) "
        "values (%s, %s, %s)",
        (f"{prefix}-key-1", f"{prefix}-lineage-1", "owner-installed-base"),
    )
    # canonical_runs carries a real foreign key to canonical_projects, so the
    # representative Run data needs its scope row first.
    _execute(
        "insert into canonical_projects (project_id, workspace_id, parent_project_id, "
        "is_root, payload) values (%s, %s, %s, %s, %s)",
        (f"{prefix}-proj", "ws-installed-base", None, True, "{}"),
    )
    _execute(
        "insert into canonical_runs (run_id, workspace_id, project_id, parent_run_id, "
        "parent_node_run_id, status, payload) values (%s, %s, %s, %s, %s, %s, %s)",
        (
            f"{prefix}-run-1",
            "ws-installed-base",
            f"{prefix}-proj",
            None,
            None,
            "completed",
            '{"source": "installed-base"}',
        ),
    )


def _assert_installed_base_rows_survive(prefix: str) -> None:
    assert _query(
        "select fact_id, statement, confidence, state from user_model_facts where fact_id = %s",
        (f"{prefix}-fact-1",),
    ) == [(f"{prefix}-fact-1", "prefers concise answers", 0.75, "active")]
    assert _query(
        "select lineage_id, owner_user_id from user_model_statement_keys where fact_key = %s",
        (f"{prefix}-key-1",),
    ) == [(f"{prefix}-lineage-1", "owner-installed-base")]
    assert _query(
        "select run_id, workspace_id, project_id, status from canonical_runs where run_id = %s",
        (f"{prefix}-run-1",),
    ) == [(f"{prefix}-run-1", "ws-installed-base", f"{prefix}-proj", "completed")]


def _assert_planner_artifacts_present() -> None:
    indexes = {
        str(row[0])
        for row in _query(
            "select indexname from pg_indexes where schemaname = 'public' and indexname = any(%s)",
            (list(PLANNER_INDEXES),),
        )
    }
    assert indexes == set(PLANNER_INDEXES), (
        f"planner indexes lost: {set(PLANNER_INDEXES) - indexes}"
    )
    assert _query(
        "select count(*) from pg_constraint where conname = %s and conrelid = "
        "'canonical_runs'::regclass",
        (PLANNER_CHECK,),
    ) == [(1,)]


def _assert_goal_upgrade_completed() -> None:
    """The assertions every installed-base fixture makes at the candidate head."""
    assert _stamp() == GOAL_REVISION
    tables = _tables()
    missing = set(GOAL_TABLES) - tables
    assert not missing, f"the Goal DDL did not apply: {missing}"
    _assert_planner_artifacts_present()


async def _drive_and_reopen_the_durable_composition(prefix: str) -> None:
    """Write Goals and a bound Run, close everything, read it back fresh.

    The supported durable composition is one database carrying the Goal
    tables (created by the upgrade, not by the stores) and the canonical
    spine together — exactly what a PostgreSQL deployment holds after
    `alembic upgrade head`.
    """
    import asyncpg

    from maistro.goals import GoalRevisionDraft, GoalStatus
    from maistro.goals.pg_store import PgGoalStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs import RunStatus
    from maistro.runs.admission import admit_direct_work
    from maistro.runs.pg_store import PgRunStore

    workspace = f"ws-{prefix}"

    async def open_pool() -> asyncpg.Pool:
        return await asyncpg.create_pool(_asyncpg_dsn(), min_size=1, max_size=2)

    # --- first process: write everything, then close the pool ------------
    pool = await open_pool()
    projects = PgProjectScopeStore(pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace,
        parent_project_id=root.project_id,
        name="Installed base",
    )
    project_id = project.project_id
    goals = PgGoalStore(pool)
    goal = await goals.create_goal(
        workspace_id=workspace,
        project_id=project_id,
        agent_id="agent-installed",
        draft=GoalRevisionDraft(desired_state="first shape", author="op-1"),
    )
    goal = await goals.append_revision(
        goal.goal_id,
        GoalRevisionDraft(desired_state="second shape", author="op-1"),
        expected_revision=1,
    )
    runs = PgRunStore(pool, project_store=projects)
    run = await admit_direct_work(
        runs,
        workspace_id=workspace,
        project_id=project_id,
        node_type="transform.format_markdown",
        name="work the goal",
        source="test",
        actor_principal_id="op-1",
        goal_id=goal.goal_id,
        goal_revision=2,
    )
    await runs.transition_run(run.run_id, RunStatus.QUEUED)
    await pool.close()

    # --- second process: fresh stores over the upgraded database ---------
    # The scope tree already lives in the database; a fresh store reads it,
    # it does not create it again (one Root Project per Workspace is a
    # database-enforced unique index).
    pool_after = await open_pool()
    try:
        projects_after = PgProjectScopeStore(pool_after)
        goals_after = PgGoalStore(pool_after)
        runs_after = PgRunStore(pool_after, project_store=projects_after)

        read_goal = await goals_after.get_goal(goal.goal_id)
        assert read_goal.status is GoalStatus.ACTIVE
        assert read_goal.current_revision == 2
        chain = await goals_after.list_goal_revisions(goal.goal_id)
        assert [revision.revision for revision in chain] == [1, 2]
        assert [revision.desired_state for revision in chain] == ["first shape", "second shape"]

        read_run = await runs_after.get_run(run.run_id)
        assert read_run is not None
        assert (read_run.goal_id, read_run.goal_revision) == (goal.goal_id, 2), (
            "the Run kept the revision it was admitted against"
        )
    finally:
        await pool_after.close()


class TestTheMergedIdentities:
    def test_merged_ids_keep_their_meaning_and_goals_appends_after_them(
        self, script_directory
    ) -> None:
        """No server needed: the graph itself is the installed-base contract.

        ``056`` must still parent on the quota door (the user-model tables),
        ``057`` on ``056`` (planner stability), and the Goal store must take
        a fresh id off the integrated head. On the renamed tree this fails
        twice: ``056`` was the Goal store and ``058`` was the planner.
        """
        revisions = {rev.revision: rev for rev in script_directory.walk_revisions()}
        assert revisions["056"].down_revision == "043_invocation_quota_door"
        assert revisions["057"].down_revision == "056"
        assert revisions["058"].down_revision == "057"
        assert revisions["059"].down_revision == "058"
        assert revisions["060"].down_revision == "059"
        assert revisions["061"].down_revision == "060"
        assert revisions[GOAL_REVISION].down_revision == "061"
        assert script_directory.get_heads() == [GOAL_REVISION]
        # The filenames carry the merged identities too — a renamed file
        # and a moved id are the same silent reassignment in two clothes.
        assert (VERSIONS / "056_user_model_facts.py").is_file()
        assert (VERSIONS / "057_run_store_planner_stability.py").is_file()
        assert (VERSIONS / "058_learning_validation_provenance.py").is_file()
        assert (VERSIONS / "059_backlog_work_source.py").is_file()
        assert (VERSIONS / "060_backlog_authority_cutover.py").is_file()
        assert (VERSIONS / HITL_FILE.rsplit("/", 1)[-1]).is_file()
        assert (VERSIONS / "062_canonical_goals.py").is_file()

    def test_restored_files_are_byte_identical_to_the_merged_snapshots(self) -> None:
        """The merged revisions' content is what develop shipped, byte for byte.

        Skips when a shallow checkout lacks the merge commits; the graph-shape
        test above still holds everywhere."""
        if not all(_have_commit(sha) for sha in (USER_MODEL_MERGE, PLANNER_MERGE, HITL_MERGE)):
            pytest.skip("develop merge commits are not present in this checkout")
        for sha, relative in (
            (USER_MODEL_MERGE, USER_MODEL_FILE),
            (PLANNER_MERGE, PLANNER_FILE),
            (HITL_MERGE, HITL_FILE),
        ):
            expected = subprocess.run(
                ["git", "show", f"{sha}:{relative}"],
                cwd=ROOT,
                capture_output=True,
                check=True,
            ).stdout
            assert (ROOT / relative).read_bytes() == expected, (
                f"{relative} drifted from what {sha[:7]} merged"
            )


class TestInstalledBaseUpgrades:
    @PG_MARK
    def test_a_database_at_merged_056_has_user_model_tables_and_no_goal_tables(
        self, empty_database
    ) -> None:
        """The regression this suite exists for, named directly.

        On the renamed tree `upgrade 056` created the *Goal* tables and no
        user-model tables — so this exact read of the live catalog failed on
        both halves. With the restored identities it holds, and the forward
        upgrade then adds the Goal DDL an installed base is still missing.
        """
        assert _alembic("upgrade", "056").returncode == 0
        tables = _tables()
        assert set(USER_MODEL_TABLES) <= tables
        assert set(GOAL_TABLES) & tables == set(), "056 must not be the Goal store"
        assert _stamp() == "056"

        _insert_installed_base_rows("at056")
        # The normal forward command, no stamp edit, no reset.
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_goal_upgrade_completed()
        _assert_installed_base_rows_survive("at056")

    @PG_MARK
    def test_an_installed_base_built_by_develop_c560d4c_forward_upgrades(
        self, empty_database, tmp_path
    ) -> None:
        """A real pre-Goal database: migrated by the actual snapshot tree.

        The snapshot's own alembic directory runs the upgrade, so the schema,
        the DDL and the stamp are the ones ``c560d4c`` produced — then the
        candidate tree takes the same database forward with the ordinary
        command."""
        if not _have_commit(USER_MODEL_MERGE):
            pytest.skip("develop merge commits are not present in this checkout")
        snapshot = _snapshot_tree(USER_MODEL_MERGE, tmp_path / "c560d4c")
        built = _alembic("upgrade", "head", cwd=snapshot)
        assert built.returncode == 0, built.stderr
        assert _stamp() == "056", "the snapshot tree must stand at its own head"
        assert set(GOAL_TABLES) & _tables() == set()

        _insert_installed_base_rows("c560d4c")
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_goal_upgrade_completed()
        _assert_installed_base_rows_survive("c560d4c")

    @PG_MARK
    def test_an_installed_base_built_by_develop_4675101_forward_upgrades(
        self, empty_database, tmp_path
    ) -> None:
        """Same walk from the planner snapshot: stamped ``057``, planner
        artifacts already in place, only the Goal DDL left to apply."""
        if not _have_commit(PLANNER_MERGE):
            pytest.skip("develop merge commits are not present in this checkout")
        snapshot = _snapshot_tree(PLANNER_MERGE, tmp_path / "4675101")
        built = _alembic("upgrade", "head", cwd=snapshot)
        assert built.returncode == 0, built.stderr
        assert _stamp() == "057", "the snapshot tree must stand at its own head"
        assert set(GOAL_TABLES) & _tables() == set()
        _assert_planner_artifacts_present()

        _insert_installed_base_rows("pl4675101")
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_goal_upgrade_completed()
        _assert_installed_base_rows_survive("pl4675101")

    @PG_MARK
    async def test_an_installed_base_at_hitl_061_forward_upgrades(
        self, empty_database, tmp_path
    ) -> None:
        """Landed 061 means HITL, not Goals: never skip the new Goal DDL."""
        if not _have_commit(HITL_MERGE):
            pytest.skip("develop HITL merge commit is not present in this checkout")
        snapshot = _snapshot_tree(HITL_MERGE, tmp_path / "hitl061")
        built = _alembic("upgrade", "head", cwd=snapshot)
        assert built.returncode == 0, built.stderr
        assert _stamp() == "061"
        assert set(GOAL_TABLES) & _tables() == set()
        hitl_index = _query(
            "select indexdef from pg_indexes where schemaname = 'public' "
            "and indexname = 'ix_graph_continuations_hitl_paused'"
        )
        assert len(hitl_index) == 1
        _insert_installed_base_rows("hitl061")

        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_goal_upgrade_completed()
        _assert_installed_base_rows_survive("hitl061")
        assert (
            _query(
                "select indexdef from pg_indexes where schemaname = 'public' "
                "and indexname = 'ix_graph_continuations_hitl_paused'"
            )
            == hitl_index
        )
        await _drive_and_reopen_the_durable_composition("hitl061")

    @PG_MARK
    @pytest.mark.parametrize("snapshot_commit", [USER_MODEL_MERGE, PLANNER_MERGE])
    async def test_the_upgraded_base_serves_the_durable_goal_composition(
        self, empty_database, tmp_path, snapshot_commit
    ) -> None:
        """After the upgrade the product can use what it built: Goals,
        revisions and immutable bound Run provenance, written and then read
        back through fresh stores on the upgraded schema."""
        if not _have_commit(snapshot_commit):
            pytest.skip("develop merge commits are not present in this checkout")
        snapshot = _snapshot_tree(snapshot_commit, tmp_path / "installed-comp")
        built = _alembic("upgrade", "head", cwd=snapshot)
        assert built.returncode == 0, built.stderr
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_goal_upgrade_completed()
        await _drive_and_reopen_the_durable_composition("installed-base-comp")
