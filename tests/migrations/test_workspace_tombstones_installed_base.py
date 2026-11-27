"""The #37 tombstone/Project-FK revision against an installed-base shape.

`072_workspace_tombstones_and_project_fk` quarantines every orphan Project
(a Project whose Workspace id owns no canonical Workspace) and then purges
the quarantined rows leaf-first, excluding the rows whose history forbids
deletion. Two foreign keys forbid it, and the purge must honor both:

* `canonical_runs.project_id` — ``ON DELETE RESTRICT`` (012),
* `design_creative_briefs.project_id` — ``ON DELETE RESTRICT`` (050).

The brief FK is the installed-base trap: a database where an orphan Project
owns a CreativeBrief but never ran anything has no `canonical_runs` row to
protect it, so a purge predicate that checks only Runs admits the Project as
a leaf — and one RESTRICT violation aborts the whole DELETE statement, every
leaf in that pass with it, and the entire upgrade transaction with both. The
predicate must exclude brief-owning Projects exactly as it excludes
run-owning ones.

This suite builds that shape on a real server: upgrade to `070` (the
pre-#37 world), write the installed-base rows, then run the ordinary
`alembic upgrade head` and assert the disposition. The purge must still
remove genuinely disposable leaves (an orphan with neither Runs nor briefs
nor children), while the run-owning and brief-owning orphans stay live,
quarantined with provenance. `canonical_projects` admits one Root per
Workspace (`ix_canonical_projects_one_root`), so the orphan Workspace's
Root is the run owner and the brief owner hangs beneath it with its own
disposable child and a bare leaf — a shape the buggy predicate walks
straight into: the bare leaves go first, the childless brief owner is
admitted next, and the brief's RESTRICT kills the whole DELETE.

Needs a real PostgreSQL server and skips without one
(``MAISTRO_TEST_DATABASE_URL``); a skipped leg is untested rather than
passing, and CI's ``postgres`` job owns a migrated server.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

#: The revision recorded while the chain sits exactly where the fences find
#: it: develop's tip before the #37 fences appended. An installed base at
#: ``070`` walks develop's landed ``071`` (Sentinel decision integrity) and
#: then ``072`` — the fences — as the append-only rungs to the head.
PRE_FENCES = "070"

QUARANTINE_REASON = "workspace_missing_at_fk_adoption"

#: One Workspace id nothing canonical owns, four orphan Projects under it:
#: ``run-owner`` is the Workspace's one Root and owns a Run; ``brief-parent``
#: hangs beneath it and owns a CreativeBrief; ``brief-child`` and ``leaf``
#: own nothing. The purge must take the two bare leaves and stop at the two
#: protected owners — with only the Run check, the second pass admits
#: ``brief-parent`` (childless by then, runless) and the brief's RESTRICT
#: kills the upgrade.
ORPHAN_WORKSPACE = "ws-orphan-legacy"


def _alembic(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """alembic/env.py resolves one URL through `require_database_url` (#187)."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=cwd,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _execute(sql: str, params: tuple[object, ...] = ()) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def _drop_all_tables() -> None:
    for (name,) in _query("select tablename from pg_tables where schemaname = 'public'"):
        quoted = str(name).replace('"', '""')
        _execute(f'drop table if exists "{quoted}" cascade')


@pytest.fixture
def installed_base_at_070():
    """One database per test, built to the pre-#37 shape, restored after.

    The teardown re-migrates to ``head`` because this module shares the
    tests/migrations PostgreSQL run: later modules expect the migrated head,
    not an empty database."""
    _alembic("downgrade", "base")
    _drop_all_tables()
    built = _alembic("upgrade", PRE_FENCES)
    assert built.returncode == 0, built.stderr
    assert _query("select version_num from alembic_version") == [(PRE_FENCES,)]
    _insert_orphan_installed_base()
    yield
    _alembic("downgrade", "base")
    _drop_all_tables()
    restored = _alembic("upgrade", "head")
    assert restored.returncode == 0, restored.stderr


def _insert_orphan_installed_base() -> None:
    """The installed-base rows, written at ``070`` through plain SQL.

    ``ws-orphan-legacy`` owns no canonical Workspace — the shape the `NOT
    VALID` fence deliberately does not scan — while ``ws-live`` is a real
    Workspace whose Project must come through the upgrade untouched, so the
    test cannot pass by the fence merely refusing everything."""
    _execute(
        """
        insert into canonical_workspaces (workspace_id, name, created_at, updated_at, payload)
        values ('ws-live', 'Live', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}')
        """
    )
    _execute(
        """
        insert into canonical_projects (project_id, workspace_id, parent_project_id,
                                        is_root, payload)
        values ('run-owner', 'ws-orphan-legacy', null, true, '{}'),
               ('brief-parent', 'ws-orphan-legacy', 'run-owner', false, '{}'),
               ('brief-child', 'ws-orphan-legacy', 'brief-parent', false, '{}'),
               ('leaf', 'ws-orphan-legacy', 'brief-parent', false, '{}'),
               ('live-proj', 'ws-live', null, true, '{}')
        """
    )
    _execute(
        """
        insert into canonical_runs (run_id, workspace_id, project_id, parent_run_id,
                                    parent_node_run_id, status, payload)
        values ('run-legacy', 'ws-orphan-legacy', 'run-owner', null, null,
                'completed', '{"source": "installed-base"}')
        """
    )
    _execute(
        """
        insert into design_creative_briefs (brief_id, lineage_id, version,
                                            supersedes_brief_id, workspace_id,
                                            project_id, goal_id, goal_revision,
                                            payload, created_by)
        values ('brief-legacy', 'lineage-legacy', 1, null, 'ws-orphan-legacy',
                'brief-parent', 'goal-legacy', 1,
                '{"source": "installed-base"}', 'op-1')
        """
    )


class TestBriefOwningOrphansSurviveThePurge:
    def test_a_brief_owning_orphan_does_not_abort_the_upgrade(self, installed_base_at_070) -> None:
        """The regression, end to end: the upgrade must complete, not abort.

        With a purge predicate that checks only `canonical_runs`, the first
        leaf pass deletes `leaf` and `brief-child`, the second admits
        `brief-parent` (childless by then, it owns no Run) and the DELETE
        dies on the brief's RESTRICT — `result.returncode != 0`, the whole
        transaction rolled back.
        """
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr

        # The brief owner and the run owner keep their live rows: both own
        # `ON DELETE RESTRICT` history the disposition is not authorized to
        # rewrite. The brief owner's disposable descendants do not enjoy the
        # same shelter — they own no protecting history, so the leaf-first
        # walk owes them nothing and takes them.
        live = {row[0] for row in _query("select project_id from canonical_projects")}
        assert {"brief-parent", "run-owner", "live-proj"} <= live
        assert "leaf" not in live, "a disposable leaf must still be purged"
        assert "brief-child" not in live, "a bare child of a protected owner is still purged"

        # Every orphan row was quarantined with its provenance before the
        # purge, including the ones the purge could not delete.
        quarantined = dict(
            _query("select project_id, reason from canonical_orphan_project_quarantine")
        )
        assert set(quarantined) == {"brief-parent", "brief-child", "run-owner", "leaf"}
        assert set(quarantined.values()) == {QUARANTINE_REASON}

        # The protected history itself is untouched.
        assert _query(
            "select brief_id, project_id from design_creative_briefs where brief_id = 'brief-legacy'"
        ) == [("brief-legacy", "brief-parent")]
        assert _query(
            "select run_id, project_id, status from canonical_runs where run_id = 'run-legacy'"
        ) == [("run-legacy", "run-owner", "completed")]

        # The tombstone fence the rest of #37 promised: the orphan's
        # Workspace id is recorded as deleted, and the live Workspace's is
        # not.
        tombstoned = {
            row[0] for row in _query("select workspace_id from canonical_workspace_deletions")
        }
        assert tombstoned == {ORPHAN_WORKSPACE}

        # The Project → Workspace fence is in place for new rows and was
        # deliberately left `NOT VALID` over the surviving installed base.
        constraint = _query(
            "select convalidated from pg_constraint where conname = "
            "'fk_canonical_projects_workspace' and conrelid = 'canonical_projects'::regclass"
        )
        assert constraint == [(False,)]
