"""The 064 legacy-principal migration against a live PostgreSQL (#1095).

`tests/test_legacy_principal_migration.py` reads the migration's SQL and checks
the shape of the plan. That is not evidence the plan *executes*: an
`ON CONFLICT` that names a constraint the live schema does not have, a column
the chain spells differently, or a merge that loses a row all look identical to
the string check until a server is actually there. #1095's acceptance is about
loss, so this suite runs the real chain on a real PostgreSQL and asserts on the
rows that survive.

Three scenarios, one per acceptance line that string checks cannot reach:

* **Mixed old/new data migrates losslessly.** A deployment that already wrote
  `conductor` rows beside installer-era `default` rows is the interesting one:
  the merge has to keep the owner role, the earliest membership timestamp, the
  union of grants, and the summed abuse history — not the last writer's.
* **Forced process death rolls back completely.** The migration is one
  transaction under transactional DDL. The test blocks it mid-flight on a table
  lock, SIGKILLs the process — the failure mode a container OOM or a node loss
  actually produces — and asserts the database is byte-for-byte pre-migration:
  both 035 heads still recorded, no mapping table, `default` rows intact.
  A restart then reconciles to the identical converged state, which is what
  "restart-reconcilable" means as an observable behavior rather than a hope.
* **Two replicas converge.** The container entrypoint serializes migration with
  a session-level advisory lock; two of them racing is the deployment shape the
  acceptance calls "two-replica migration attempts". Both must succeed, and the
  mapping must end singular: `default -> conductor`, once.

Needs a real server and skips without one, exactly like
`tests/migrations/test_migration_chain.py`: `MAISTRO_TEST_DATABASE_URL` is what
makes it run, and `ci.yml`'s `postgres` job sets it. The skip is deliberate —
a laptop without PostgreSQL gets a skip, not a false pass — but the CI wiring
is the part that keeps this suite from silently never running.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

#: The revision recorded while the chain sits exactly where 064 will find it:
#: develop's integrated head, after which 064 appends.
PRE_064_VERSIONS = frozenset({"063"})

#: Installer-era and post-installer principals side by side in every surface
#: 064 touches, so each merge branch has a row to converge.
SEED = """
insert into canonical_workspaces (workspace_id, name, created_at, updated_at, payload)
values ('ws1', 'Workspace One', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}'),
       ('ws2', 'Workspace Two', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}');

-- The interesting overlap: default joined *first* as a member, conductor
-- arrived later as owner. Owner must win the role, the earliest added_at must
-- survive, and the payload must stop naming the retired principal.
insert into canonical_workspace_memberships (workspace_id, user_id, role, added_at, payload)
values ('ws1', 'default', 'member', '2025-12-01T00:00:00Z', '{"user_id":"default","role":"member"}'),
       ('ws1', 'conductor', 'owner', '2026-01-02T00:00:00Z', '{"user_id":"conductor","role":"owner"}'),
       ('ws2', 'default', 'owner', '2025-12-05T00:00:00Z', '{"user_id":"default","role":"owner"}');

insert into canonical_projects (project_id, workspace_id, is_root, payload)
values ('proj1', 'ws1', true, '{}'), ('proj2', 'ws2', true, '{}');

-- Disjoint grant/deny/delegable arrays on the same (project, principal)
-- boundary: the merge must keep every right either side ever had.
insert into canonical_project_memberships (membership_id, workspace_id, project_id, principal_id, payload)
values ('m-p1-default', 'ws1', 'proj1', 'default', '{"principal_id":"default","grants":["read"],"denies":[],"delegable_grants":["delegate"]}'),
       ('m-p1-conductor', 'ws1', 'proj1', 'conductor', '{"principal_id":"conductor","grants":["write"],"denies":["delete"],"delegable_grants":[]}'),
       ('m-p2-default', 'ws2', 'proj2', 'default', '{"principal_id":"default","grants":["run"],"denies":[],"delegable_grants":[]}');

insert into learnings (trigger_keys, learning, tool_name, user_id, org_id)
values ('["k"]', 'legacy learning', 'tool', 'default', 'default'), ('["k2"]', 'new learning', 'tool', 'conductor', 'conductor');

insert into episodic_memories (memory_id, tier, content, user_id, org_id)
values ('mem-default', 'hot', 'legacy memory', 'default', 'default'), ('mem-conductor', 'hot', 'new memory', 'conductor', 'conductor');

insert into outcomes (request_id, user_id, org_id) values ('req-default', 'default', 'default'), ('req-conductor', 'conductor', 'conductor');
insert into audit_log (user_id, org_id) values ('default', 'default'), ('conductor', 'conductor');

-- Task visibility is scoped by the authenticated principal (the API passes
-- ``user_id=owner`` into every task read), so a task owned by the installer-era
-- principal must follow the identity or the migrated operator loses it.
insert into tasks (id, status, description, workspace, user_id, actor_kind, lane, priority_tier)
values ('task-default', 'queued', 'legacy task', 'ws1', 'default', 'user', 'interactive', 'P2'),
       ('task-conductor', 'queued', 'new task', 'ws1', 'conductor', 'user', 'interactive', 'P2');

insert into design_projects (name, skill_slug, design_system_slug, org_id)
values ('Legacy', 's', 'ds', 'default'), ('New', 's', 'ds', 'conductor');
insert into child_profiles (profile_id, name, org_id)
values ('cp-default', 'Legacy Child', 'default'), ('cp-conductor', 'New Child', 'conductor');
insert into asset_definitions (asset_id, kind, base_prompt, org_id)
values ('ad-default', 'kind', 'prompt', 'default'), ('ad-conductor', 'kind', 'prompt', 'conductor');
insert into asset_instances (instance_id, canvas_id, definition_id, org_id)
values ('ai-default', 'canvas1', 'ad-default', 'default'), ('ai-conductor', 'canvas1', 'ad-conductor', 'conductor');
insert into books (book_id, title, world_style, org_id)
values ('book-default', 'Legacy Book', '{}', 'default'), ('book-conductor', 'New Book', '{}', 'conductor');

-- The Canvas owner column is the authenticated principal (`_owner_id(auth)`);
-- a canvas whose org_id no longer matches 404s for the migrated operator.
insert into canvases (id, name, width, height, org_id)
values ('canvas-default', 'Legacy Canvas', 1024, 768, 'default'),
       ('canvas-conductor', 'New Canvas', 1024, 768, 'conductor');

-- Durable elevation grants name who may hold an elevated capability.
insert into elevation_grants (principal_id, action_class, kind, granted_at, ttl_seconds, signed_by)
values ('default', 'tool.invoke', 'temporary', '2026-01-01T00:00:00Z'::timestamptz, 3600, 'test-signer'),
       ('conductor', 'tool.invoke', 'temporary', '2026-01-02T00:00:00Z'::timestamptz, 3600, 'test-signer');

-- default carries more strikes but is not disabled; conductor is. The merged
-- principal must sum the history and stay disabled: neither side's abuse state
-- may be reset by the identity change.
insert into security_strikes (user_id, strike_count, scrutiny_level, locked_until, disabled, last_violation_at, created_at, updated_at)
values ('default', 2, 'elevated', '2026-02-01T00:00:00Z', false, '2026-01-15T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-15T00:00:00Z'),
       ('conductor', 1, 'normal', null, true, '2026-01-10T00:00:00Z', '2026-01-02T00:00:00Z', '2026-01-10T00:00:00Z');
insert into security_violations (user_id, flags, boundary, detail)
values ('default', '{prompt_injection}', 'user_input', 'legacy violation');

-- Two windows: one where both principals already have history to sum, one
-- only the legacy principal touched, so the retarget of a lone bucket is
-- covered beside the merge of an overlapping one.
insert into security_rate_limits (key, window_start, count)
values ('principal:default', '2026-03-01T00:00:00Z', 4),
       ('principal:conductor', '2026-03-01T00:00:00Z', 1),
       ('principal:default', '2026-03-02T00:00:00Z', 7);

insert into canonical_runs (run_id, workspace_id, project_id, status, payload)
values ('run-default', 'ws1', 'proj1', 'completed', '{"actor_principal_id":"default","name":"legacy run"}'),
       ('run-conductor', 'ws1', 'proj1', 'completed', '{"actor_principal_id":"conductor","name":"new run"}');
insert into canonical_event_log (event_id, stream_id, sequence, type, timestamp, actor_id)
values ('evt-default', 'run-default', 1, 'run.completed', 1770000000.0, 'default'),
       ('evt-conductor', 'run-conductor', 1, 'run.completed', 1770000001.0, 'conductor');
-- Tasks also carry a service principal (webhook/service identity). Seed it
-- from the owning principal so the migration's tasks.service_principal_id
-- leg has a legacy and a new row to converge.
update tasks set service_principal_id = user_id;

-- learning_stage_transitions is append-only ladder audit evidence; org_id is
-- the scope label. Seed one legacy and one new row.
insert into learning_stage_transitions (learning_id, org_id, from_stage, to_stage, actor, reason)
select id, 'default', 'draft', 'published', 'default', 'legacy' from learnings where user_id = 'default' limit 1;
insert into learning_stage_transitions (learning_id, org_id, from_stage, to_stage, actor, reason)
select id, 'conductor', 'draft', 'published', 'conductor', 'new' from learnings where user_id = 'conductor' limit 1;

-- Design artifacts: org_id scopes them, created_by names the author. Seed
-- one legacy and one new row in each surface, reusing the seeded projects.
insert into design_artifact_versions (id, org_id, project_id, lineage_id, version, kind, origin, content_sha, created_at)
select gen_random_uuid(), 'default', id, 'lin-default', 1, 'kind', 'origin', 'sha', now()
  from design_projects where org_id = 'default' limit 1;
insert into design_artifact_versions (id, org_id, project_id, lineage_id, version, kind, origin, content_sha, created_at)
select gen_random_uuid(), 'conductor', id, 'lin-conductor', 1, 'kind', 'origin', 'sha', now()
  from design_projects where org_id = 'conductor' limit 1;

insert into design_artifact_locks (lock_id, org_id, project_id, lineage_id, scope, created_by, created_at)
select 'lock-default', 'default', id, 'lin-default', 'scope', 'default', now()
  from design_projects where org_id = 'default' limit 1;
insert into design_artifact_locks (lock_id, org_id, project_id, lineage_id, scope, created_by, created_at)
select 'lock-conductor', 'conductor', id, 'lin-conductor', 'scope', 'conductor', now()
  from design_projects where org_id = 'conductor' limit 1;

insert into design_branch_controls (control_id, org_id, project_id, lineage_id, mode, updated_by, updated_at)
select gen_random_uuid(), 'default', id, 'lin-default', 'mode', 'default', now()
  from design_projects where org_id = 'default' limit 1;
insert into design_branch_controls (control_id, org_id, project_id, lineage_id, mode, updated_by, updated_at)
select gen_random_uuid(), 'conductor', id, 'lin-conductor', 'mode', 'conductor', now()
  from design_projects where org_id = 'conductor' limit 1;

insert into design_project_guidance (guidance_id, org_id, project_id, text, author, created_at)
select 'guidance-default', 'default', id, 'text', 'default', now()
  from design_projects where org_id = 'default' limit 1;
insert into design_project_guidance (guidance_id, org_id, project_id, text, author, created_at)
select 'guidance-conductor', 'conductor', id, 'text', 'conductor', now()
  from design_projects where org_id = 'conductor' limit 1;

insert into design_creative_briefs (brief_id, lineage_id, version, workspace_id, project_id, goal_id, goal_revision, payload, created_by)
values ('brief-default', 'lin', 1, 'ws1', 'proj1', 'goal1', 1, '{}'::jsonb, 'default'),
       ('brief-conductor', 'lin', 2, 'ws2', 'proj2', 'goal1', 1, '{}'::jsonb, 'conductor');

insert into user_model_facts (fact_id, lineage_id, revision, owner_user_id, kind, statement, evidence, first_observed, last_observed, last_reinforced, confidence, state, sensitivity, reusable, persona_hints)
values ('fact-default', 'lin', 1, 'default', 'kind', 'stmt', '{}'::jsonb, now(), now(), now(), 0.5, 'state', 'sens', true, '{}'::jsonb),
       ('fact-conductor', 'lin', 1, 'conductor', 'kind', 'stmt', '{}'::jsonb, now(), now(), now(), 0.5, 'state', 'sens', true, '{}'::jsonb);

insert into user_model_statement_keys (fact_key, lineage_id, owner_user_id)
values ('key-default', 'lin', 'default'), ('key-conductor', 'lin', 'conductor');

"""


def _alembic_env() -> dict[str, str]:
    """alembic/env.py resolves one URL through `require_database_url` (#187)."""
    return {**os.environ, "DATABASE_URL": DATABASE_URL}


def _alembic(*args: str, timeout_s: float = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return list(cur.fetchall())


def _execute(script: str) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(script)  # type: ignore[arg-type]


def _versions() -> set[str]:
    return {str(row[0]) for row in _query("select version_num from alembic_version")}


def _table_exists(name: str) -> bool:
    return bool(_query("select to_regclass(%s) is not null", (f"public.{name}",))[0][0])


def _column_values(table: str, column: str) -> list[object]:
    # Callers are this module's fixed table list; the interpolation is not
    # reachable from test data. Ordered so the comparisons below are about
    # which rows survived, not about heap order.
    return [row[0] for row in _query(f"select {column} from {table} order by {column}")]


@pytest.fixture
def mixed_pre_064_database():
    """The database as an upgraded deployment sat when 064 ships: develop's
    integrated chain applied, and rows written under both the installer-era
    `default` principal and the `conductor` that replaced it.

    `downgrade base` from any state this suite leaves is unambiguous, so one
    reset serves every test regardless of where the previous one died.
    """
    result = _alembic("downgrade", "base")
    assert result.returncode == 0, result.stderr
    # One linear chain: walking to the revision 064 revises is a single
    # upgrade. The chain itself is what `test_migration_chain.py` proves;
    # here it only has to land exactly on 063.
    assert _alembic("upgrade", "063").returncode == 0
    assert _versions() == PRE_064_VERSIONS
    _execute(SEED)
    yield
    assert _alembic("downgrade", "base").returncode == 0


def _assert_losslessly_migrated() -> None:
    """Assert the converged state every path below must reach.

    Spelled out per table rather than as one bulk "no default anywhere" scan:
    that scan would pass if a merge silently dropped a row, which is precisely
    the loss this issue exists to prevent.
    """
    # The durable mapping: one row, and it is the supported one.
    assert _query(
        "select legacy_principal, canonical_principal from principal_identity_mappings"
    ) == [("default", "conductor")]

    memberships = _query(
        """
        select workspace_id, user_id, role, added_at::text, payload
          from canonical_workspace_memberships
         order by workspace_id
        """
    )
    assert memberships == [
        # ws1: role owner (either side held it), added_at the *earliest* of the
        # two, payload naming only the surviving principal.
        (
            "ws1",
            "conductor",
            "owner",
            "2025-12-01 00:00:00+00",
            {"user_id": "conductor", "role": "owner"},
        ),
        # ws2: the legacy-only workspace carries its owner forward untouched
        # apart from the principal.
        (
            "ws2",
            "conductor",
            "owner",
            "2025-12-05 00:00:00+00",
            {"user_id": "conductor", "role": "owner"},
        ),
    ]

    projects = _query(
        """
        select project_id, principal_id, payload
          from canonical_project_memberships
         order by project_id
        """
    )
    assert [(p[0], p[1]) for p in projects] == [("proj1", "conductor"), ("proj2", "conductor")]
    proj1, proj2 = (json.dumps(p[2]) for p in projects)
    # proj1 kept conductor's membership row and the union of both sides' rights.
    assert json.loads(proj1)["grants"] == ["write", "read"]
    assert json.loads(proj1)["denies"] == ["delete"]
    assert json.loads(proj1)["delegable_grants"] == ["delegate"]
    # proj2's grants moved with it.
    assert json.loads(proj2)["grants"] == ["run"]

    # Append-only evidence: both rows survive, retargeted, none dropped. The
    # org scope labels ride the same identity (same installer-era value).
    for table in ("learnings", "episodic_memories", "outcomes", "audit_log"):
        assert _column_values(table, "user_id") == ["conductor", "conductor"], table
        assert _column_values(table, "org_id") == ["conductor", "conductor"], table
    for table in (
        "design_projects",
        "child_profiles",
        "asset_definitions",
        "asset_instances",
        "books",
    ):
        assert _column_values(table, "org_id") == ["conductor", "conductor"], table

    # Task ownership follows the identity: the migrated operator still sees
    # every task the legacy principal owned, and loses none to the rename.
    assert _column_values("tasks", "user_id") == ["conductor", "conductor"]
    # Service-principal scoping follows the identity too.
    assert _column_values("tasks", "service_principal_id") == ["conductor", "conductor"]
    # Canvas ownership too: org_id is the authenticated owner, and a stale one
    # 404s the operator out of their own canvas.
    assert _query("select id, org_id from canvases order by id") == [
        ("canvas-conductor", "conductor"),
        ("canvas-default", "conductor"),
    ]

    # learning_stage_transitions org_id scope label follows the identity.
    assert _column_values("learning_stage_transitions", "org_id") == ["conductor", "conductor"]

    # Design artifact ownership surfaces: org_id scopes, created_by names author.
    for table in (
        "design_artifact_versions",
        "design_artifact_locks",
        "design_branch_controls",
        "design_project_guidance",
    ):
        assert _column_values(table, "org_id") == ["conductor", "conductor"], table
    assert _column_values("design_artifact_locks", "created_by") == ["conductor", "conductor"]
    assert _column_values("design_creative_briefs", "created_by") == ["conductor", "conductor"]

    # User-model ownership boundaries follow the identity.
    assert _column_values("user_model_facts", "owner_user_id") == ["conductor", "conductor"]
    assert _column_values("user_model_statement_keys", "owner_user_id") == [
        "conductor",
        "conductor",
    ]
    # Durable elevation grants keep granting to the migrated principal.
    assert _query("select principal_id from elevation_grants order by id") == [
        ("conductor",),
        ("conductor",),
    ]

    # Abuse state summed, never reset: 2 + 1 strikes, still disabled, the
    # later violation timestamp, and the violation row retargeted with it.
    assert _query(
        """
        select user_id, strike_count, disabled, last_violation_at::text
          from security_strikes
        """
    ) == [("conductor", 3, True, "2026-01-15 00:00:00+00")]
    assert _query("select user_id from security_violations") == [("conductor",)]

    rate_limits = _query(
        """
        select key, window_start::text, count
          from security_rate_limits
         order by window_start
        """
    )
    assert rate_limits == [
        # Overlapping window: histories summed.
        ("principal:conductor", "2026-03-01 00:00:00+00", 5),
        # Lone legacy window: retargeted, count intact.
        ("principal:conductor", "2026-03-02 00:00:00+00", 7),
    ]

    # Run provenance and the event log follow the actor; the mapping row is
    # what preserves the historical fact they were written under `default`.
    assert _query(
        "select run_id, payload->>'actor_principal_id' from canonical_runs order by run_id"
    ) == [("run-conductor", "conductor"), ("run-default", "conductor")]
    assert _query("select event_id, actor_id from canonical_event_log order by event_id") == [
        ("evt-conductor", "conductor"),
        ("evt-default", "conductor"),
    ]

    # The chain tip once the replay-cursor revision (#836) renumbered past
    # 065 at the develop sync: 064 is this file's subject, 065 the Persona
    # revision, 066 the current head (test_goal_installed_base_upgrade
    # carries the same constant).
    assert _versions() == {"066"}


class TestMixedDataMigratesLosslessly:
    def test_upgrade_head_merges_every_old_and_new_row(self, mixed_pre_064_database) -> None:
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_losslessly_migrated()


class TestForcedProcessDeathIsRestartReconcilable:
    def test_sigkill_mid_migration_rolls_back_completely_then_converges(
        self, mixed_pre_064_database
    ) -> None:
        import psycopg

        # Hold the table the migration's second statement needs, so the
        # process is inside the transaction — mapping table created, version
        # row not yet written — when it dies.
        migration = subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=_alembic_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with psycopg.connect(DATABASE_URL) as blocker, blocker.cursor() as cur:
                blocker.autocommit = False
                cur.execute("LOCK TABLE canonical_workspace_memberships IN ACCESS EXCLUSIVE MODE")
                assert _wait_until_migration_is_blocked(cur), (
                    "migration never reached the locked table; the kill would not prove rollback"
                )
                os.kill(migration.pid, signal.SIGKILL)
                assert migration.wait(timeout=60) == -signal.SIGKILL
                blocker.rollback()

            # The server discards the dead backend's transaction, but not
            # instantaneously: the queued lock request is the observable that
            # the session is really gone rather than merely killed client-side.
            assert _wait_until_lock_queue_clears(), (
                "the killed backend is still queued on the table lock"
            )
            # Rolled back totally: the chain still sits at 063, the mapping
            # table absent, and the legacy rows exactly where they started.
            assert _versions() == PRE_064_VERSIONS
            assert not _table_exists("principal_identity_mappings")
            assert _column_values("canonical_workspace_memberships", "user_id") == [
                "conductor",
                "default",
                "default",
            ]
            # Run provenance untouched as well.
            assert _query(
                "select payload->>'actor_principal_id' from canonical_runs"
                " where run_id = 'run-default'"
            ) == [("default",)]
            # Task ownership untouched too.
            assert _column_values("tasks", "user_id") == ["conductor", "default"]
            assert _column_values("tasks", "service_principal_id") == ["conductor", "default"]
        finally:
            if migration.poll() is None:  # pragma: no cover - only on assertion failure
                migration.kill()
                migration.wait(timeout=60)

        # The restart: same command, from the rolled-back state.
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        _assert_losslessly_migrated()


class TestTwoReplicasConverge:
    def test_both_entrypoints_succeed_and_end_with_one_mapping(
        self, mixed_pre_064_database
    ) -> None:
        """Two containers racing the same upgrade, through the real entrypoint
        serialization: the advisory lock orders them, and the loser must see a
        database already at head rather than erroring on half of it."""
        # The root dev environment installs maistro-core but not
        # maistro-server (pytest's `pythonpath` supplies it in-process); the
        # subprocess needs the package's src on PYTHONPATH explicitly, which is
        # also what the shipped image installs.
        env = {
            **_alembic_env(),
            "PYTHONPATH": str(ROOT / "packages" / "maistro-server" / "src"),
        }
        replicas = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from maistro_server.entrypoint import run_migrations; run_migrations()",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        try:
            for replica in replicas:
                stdout, stderr = replica.communicate(timeout=300)
                assert replica.returncode == 0, stderr or stdout
        finally:
            for replica in replicas:
                if replica.poll() is None:  # pragma: no cover - only on failure
                    replica.kill()
                    replica.wait(timeout=60)

        _assert_losslessly_migrated()


def _wait_until_migration_is_blocked(cur, timeout_s: float = 120.0) -> bool:
    """True once some backend is queued on the membership table lock.

    The uncommitted `CREATE TABLE principal_identity_mappings` is invisible to
    this session, so the lock queue — not the catalog — is the observable that
    the migration has begun its transaction and is waiting inside it.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        cur.execute(
            """
            select l.pid
              from pg_locks l
              join pg_class c on c.oid = l.relation
             where c.relname = 'canonical_workspace_memberships'
               and not l.granted
             limit 1
            """
        )
        if cur.fetchone() is not None:
            return True
        time.sleep(0.1)
    return False


def _wait_until_lock_queue_clears(timeout_s: float = 30.0) -> bool:
    """True once no backend is queued on the membership table lock.

    After the SIGKILL this is the direct observation that PostgreSQL has
    reaped the dead session: its ungranted lock request disappears only when
    its transaction is discarded.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _query(
            "select 1 from pg_locks l join pg_class c on c.oid = l.relation"
            " where c.relname = 'canonical_workspace_memberships' and not l.granted limit 1"
        ):
            return True
        time.sleep(0.25)
    return False
