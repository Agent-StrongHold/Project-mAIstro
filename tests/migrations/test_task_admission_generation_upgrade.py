"""The forward admission-generation representation on task_idempotency (#1892).

Revision 055 gives the claim table a durable shape for immutable admission
generations (format_version 2) without touching a single legacy row: every
preexisting claim stays byte-for-byte in its original columns, keeps
``format_version = 1`` by default, and is admitted by the v2 CHECK exactly as
it stands. The v2 contract is enforced representation-side — explicit
``IS NOT NULL`` on every nullable-but-required field (PostgreSQL CHECK reads
NULL as UNKNOWN and passes it), lowercase 32-hex non-nil generation and owner
token, nonblank scope/action ids, the binding pair absent-or-present with
``task_id = receipt_id``, acknowledgement only on a bound row, and a positive
window. The exact 24-hour production TTL is a writer policy, not a schema
constant (#1851); only ``expires_at > created_at`` is representation.

Every case here runs against the live catalog on a disposable PostgreSQL
database, because the contract is what a server enforces, not what a migration
file prints. Needs a real server and skips without one, so
``MAISTRO_TEST_DATABASE_URL`` is what makes it run — same wiring as
``test_migration_chain``.

This leaf activates no writer: nothing here claims mixed old/new writers are
safe. The downgrade refusal is precisely the guard that keeps a live v2
generation from being silently handed to a writer that cannot read it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

#: Lowercase 32-hex, non-nil — the representation the v2 CHECK demands.
GENERATION_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
OWNER_TOKEN = "0f9e8d7c6b5a493827160594a3b2c1d0"
NIL_HEX = "0" * 32

#: The columns shipped 038 owns — the "old columns" whose contents must
#: survive the forward upgrade byte-for-byte.
SHIPPED_COLUMNS = (
    "scope_key",
    "fingerprint",
    "request",
    "task_id",
    "run_id",
    "created_at",
    "expires_at",
    "lease_expires_at",
)

#: Every nullable-but-required v2 field. NULL in any one of them must be
#: rejected independently — the explicit IS NOT NULL half of the contract.
V2_REQUIRED_FIELDS = (
    "generation_id",
    "claim_token",
    "workspace_id",
    "project_id",
    "origin_principal_id",
    "actor_principal_id",
    "action",
    "receipt_id",
    "receipt_snapshot",
    "provenance_snapshot",
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


def _query(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return list(cur.fetchall())


def _execute(sql: str, params: tuple[Any, ...] = ()) -> None:
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


def _drop_all_tables() -> None:
    """Empty `public` entirely — the same discipline as test_migration_chain:
    a stamp or a partial upgrade must not poison the next test."""
    for (name,) in _query("select tablename from pg_tables where schemaname = 'public'"):
        quoted = str(name).replace('"', '""')
        _execute(f'drop table if exists "{quoted}" cascade')


def _stamped_version() -> str | None:
    tables = _tables()
    if "alembic_version" not in tables:
        return None
    rows = _query("select version_num from alembic_version")
    return str(rows[0][0]) if rows else None


def _chain_head() -> str:
    """The single head of the migration chain, read from the version files.

    Every develop collision re-parents this branch's revisions onto a new
    chain tip, so a fixed literal in an assertion about "the head" is only
    ever an artifact of whichever sync wrote it — it has rotted three times
    already (043_invocation_quota_door, 055, 056). The invariant under test
    is that the refused downgrade leaves the stamp AT HEAD, so the head is
    resolved from the same scripts the upgrade above ran.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, (
        f"expected exactly one migration head, found {sorted(heads)}; "
        "see tests/migrations/test_single_migration_head.py"
    )
    return heads[0]


@pytest.fixture
def empty_database():
    """Start each test from `base`, so one failure cannot cascade into the next."""
    _alembic("downgrade", "base")
    _drop_all_tables()
    yield
    _alembic("downgrade", "base")
    _drop_all_tables()


def _shipped_row_sql(scope_key: str, *, complete: bool) -> str:
    task = f"'task-{scope_key}'"
    run = f"'run-{scope_key}'"
    if not complete:
        task = "NULL"
        run = "NULL"
    return f"""
        insert into task_idempotency
            (scope_key, fingerprint, request, task_id, run_id,
             created_at, expires_at, lease_expires_at)
        values ('{scope_key}', 'fp-{scope_key}', '{{"request":"{scope_key}"}}',
                {task}, {run}, 1000, 2000, 1500)
    """


def _shipped_rows() -> list[tuple[Any, ...]]:
    columns = ", ".join(SHIPPED_COLUMNS)
    return _query(
        f"select {columns} from task_idempotency order by scope_key",
    )


def _valid_v2_row(**overrides: Any) -> dict[str, Any]:
    """One complete, unbound-but-valid format-v2 generation."""
    row: dict[str, Any] = {
        "scope_key": "v2-claim",
        "format_version": 2,
        "generation_id": GENERATION_ID,
        "claim_token": OWNER_TOKEN,
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "origin_principal_id": "principal-1",
        "actor_principal_id": "actor-1",
        "action": "chat.run",
        "receipt_id": "receipt-1",
        "receipt_snapshot": '{"id":"receipt-1"}',
        "provenance_snapshot": '{"admitted_by":"principal-1"}',
        "request": '{"task":"original"}',
        "fingerprint": "f" * 64,
        "task_id": None,
        "run_id": None,
        "created_at": 1000,
        "expires_at": 2000,
        "lease_expires_at": 1500,
        "acknowledged_at": None,
    }
    row.update(overrides)
    return row


def _insert_v2(row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join("%s" for _ in row)
    _execute(
        f"insert into task_idempotency ({columns}) values ({placeholders})",
        tuple(row.values()),
    )


def _v2_columns() -> dict[str, dict[str, Any]]:
    return {
        str(row[0]): {"type": row[1], "nullable": row[2], "default": row[3]}
        for row in _query(
            """
            select column_name, data_type, is_nullable, column_default
            from information_schema.columns
            where table_schema = 'public' and table_name = 'task_idempotency'
            """
        )
    }


class TestTheForwardUpgrade:
    def test_forward_upgrade_preserves_shipped_038_rows(self, empty_database) -> None:
        """A database stamped at the shipped chain keeps every claim
        byte-for-byte in its original columns — complete and unbound alike —
        and both land on format_version 1 untouched."""
        assert _alembic("upgrade", "052").returncode == 0
        _execute(_shipped_row_sql("pending-claim", complete=False))
        _execute(_shipped_row_sql("complete-claim", complete=True))
        before = _shipped_rows()
        assert len(before) == 2

        assert _alembic("upgrade", "head").returncode == 0

        assert _shipped_rows() == before
        versions = dict(_query("select scope_key, format_version from task_idempotency"))
        assert versions == {"pending-claim": 1, "complete-claim": 1}

    def test_forward_upgrade_accepts_known_l41_shape(self, empty_database) -> None:
        """The #1325 integration shape (claim_token NOT NULL, completed_at
        defaulted) upgrades without re-executing 038: both legacy columns are
        retained as found, and the claim they carry survives byte-for-byte.

        The shape is reached from a real chain history — upgrade to 038, then
        re-shape the baseline into exactly the form the L41 branch's 038
        builds — so the walk forward exercises a database that arrived at the
        claim table through its own migration history, not a bare stamp."""
        assert _alembic("upgrade", "038").returncode == 0
        # The L41 reconciliation of 038 owns two columns the develop baseline
        # does not. The table is empty here, so NOT NULL lands directly; the
        # defaulted completed_at carries the L41 server default.
        _execute("alter table task_idempotency add column claim_token TEXT NOT NULL")
        _execute("alter table task_idempotency add column completed_at BIGINT NOT NULL DEFAULT 0")
        _execute(
            """
            insert into task_idempotency
                (scope_key, claim_token, fingerprint, request, task_id, run_id,
                 completed_at, created_at, expires_at, lease_expires_at)
            values ('l41-claim', %s, 'fp', 'req', 'task-1', 'run-1',
                    1234, 1000, 2000, 1500)
            """,
            (OWNER_TOKEN,),
        )
        before = _query(
            "select scope_key, claim_token, fingerprint, request, task_id, run_id, "
            "completed_at, created_at, expires_at, lease_expires_at "
            "from task_idempotency where scope_key = 'l41-claim'"
        )

        assert _alembic("upgrade", "head").returncode == 0

        columns = _v2_columns()
        # The known optional legacy evidence, exactly as shipped — NOT NULL
        # claim_token retained, defaulted completed_at retained.
        assert columns["claim_token"] == {
            "type": "text",
            "nullable": "NO",
            "default": None,
        }
        assert columns["completed_at"]["type"] == "bigint"
        assert str(columns["completed_at"]["default"]).lstrip("'").rstrip("'") == "0"
        # The forward representation arrived without rewriting the claim.
        assert (
            _query(
                "select scope_key, claim_token, fingerprint, request, task_id, run_id, "
                "completed_at, created_at, expires_at, lease_expires_at "
                "from task_idempotency where scope_key = 'l41-claim'"
            )
            == before
        )
        assert _query(
            "select format_version from task_idempotency where scope_key = 'l41-claim'"
        ) == [(1,)]
        # And the legacy row is still admitted by the v2 CHECK, as every
        # format-v1 row must be.
        assert _query("select count(*) from task_idempotency where scope_key = 'l41-claim'") == [
            (1,)
        ]

    def test_reapplied_forward_revision_adopts_exact_populated_v2_shape(
        self, empty_database
    ) -> None:
        """Stamp-back + re-upgrade over an already-applied forward shape is
        adoption: the populated v2 generation survives byte-for-byte and the
        validated shape gains nothing."""
        assert _alembic("upgrade", "head").returncode == 0
        _insert_v2(_valid_v2_row(task_id="receipt-1", run_id="run-1", acknowledged_at=3000))
        before = _query("select * from task_idempotency where scope_key = 'v2-claim'")

        assert _alembic("stamp", "052").returncode == 0
        assert _alembic("upgrade", "head").returncode == 0

        assert _query("select * from task_idempotency where scope_key = 'v2-claim'") == before
        assert _query(
            "select count(*) from pg_constraint where conname = "
            "'ck_task_idempotency_v2_identity' and conrelid = "
            "'task_idempotency'::regclass and contype = 'c'"
        ) == [(1,)]

    def test_fresh_chain_builds_the_contracted_forward_shape(self, empty_database) -> None:
        """The forward shape on a fresh chain: every contracted column with the
        contracted type and nullability, format_version defaulting to 1 — and
        no completed_at, which v2 does not need and the baseline never had."""
        assert _alembic("upgrade", "head").returncode == 0
        columns = _v2_columns()
        expected = {
            "scope_key": ("text", "NO"),
            "fingerprint": ("text", "NO"),
            "request": ("text", "NO"),
            "task_id": ("text", "YES"),
            "run_id": ("text", "YES"),
            "created_at": ("bigint", "NO"),
            "expires_at": ("bigint", "NO"),
            "lease_expires_at": ("bigint", "NO"),
            "format_version": ("smallint", "NO"),
            "generation_id": ("text", "YES"),
            "claim_token": ("text", "YES"),
            "workspace_id": ("text", "YES"),
            "project_id": ("text", "YES"),
            "origin_principal_id": ("text", "YES"),
            "actor_principal_id": ("text", "YES"),
            "action": ("text", "YES"),
            "receipt_id": ("text", "YES"),
            "receipt_snapshot": ("text", "YES"),
            "provenance_snapshot": ("text", "YES"),
            "acknowledged_at": ("bigint", "YES"),
        }
        actual = {name: (spec["type"], spec["nullable"]) for name, spec in columns.items()}
        assert actual == expected, f"unexpected forward shape: {sorted(actual)}"
        assert str(columns["format_version"]["default"]) == "1"
        assert "completed_at" not in columns

    def test_unknown_shape_does_not_advance_revision(self, empty_database) -> None:
        """A claim table whose shape is not the shipped one refuses to be
        stamped forward: revision 055 validates before it writes, the upgrade
        aborts, and the stamp stays at the last good revision with no forward
        DDL applied."""
        # A real chain history, then a corruption the shipped chain never
        # built: created_at as text. This is the shape an operator would have
        # to reconcile by hand — the migration refuses to adopt it.
        assert _alembic("upgrade", "052").returncode == 0
        _execute("alter table task_idempotency alter column created_at type text")

        result = _alembic("upgrade", "head")

        assert result.returncode != 0, "a wrong-typed claim table upgraded cleanly"
        # The upgrade run is one transaction: develop's 053 (learning-lifecycle
        # columns on `learnings`) and this branch's 054 (learning
        # applicability, #119) roll back together with the refusing 055, so
        # the stamp stays at the last good revision, 052.
        assert _stamped_version() == "052", "the revision advanced over an unknown shape"
        # The refusal names the incompatible shape rather than dying quietly.
        assert "incompatible baseline shape" in result.stderr + result.stdout
        assert _v2_columns().get("generation_id") is None
        assert _v2_columns().get("format_version") is None

    def test_malformed_key_or_index_does_not_advance_revision(self, empty_database) -> None:
        """The same refusal for the key and index halves of the shape: no
        primary key on scope_key (the key IS the claim), or a lost expiry
        index (the purge scan bound), and revision 055 will not stamp."""
        assert _alembic("upgrade", "052").returncode == 0

        # Phase 1: the primary key is gone.
        _execute("alter table task_idempotency drop constraint pk_task_idempotency")
        result = _alembic("upgrade", "head")
        assert result.returncode != 0, "a keyless claim table upgraded cleanly"
        assert "primary key" in result.stderr + result.stdout
        assert _stamped_version() == "052"
        assert _v2_columns().get("format_version") is None

        # Phase 2: the key restored but the purge index lost.
        _execute(
            "alter table task_idempotency add constraint pk_task_idempotency "
            "primary key (scope_key)"
        )
        _execute("drop index ix_task_idempotency_expires")
        result = _alembic("upgrade", "head")
        assert result.returncode != 0, "an indexless claim table upgraded cleanly"
        assert "ix_task_idempotency_expires" in result.stderr + result.stdout
        assert _stamped_version() == "052"
        assert _v2_columns().get("format_version") is None

    def test_pre_038_runtime_table_blocks_the_chain_before_this_revision(
        self, empty_database
    ) -> None:
        """A runtime-provisioned table with PRE-038 history is explicitly
        blocked — by shipped 038 itself, before this forward revision can run.
        No blind stamping conceals it; reconciling it is an operator action."""
        _execute("create table task_idempotency (scope_key TEXT PRIMARY KEY, note TEXT)")

        result = _alembic("upgrade", "head")

        assert result.returncode != 0, "the chain stamped over a foreign table"
        assert _stamped_version() in (None, ""), "the chain advanced despite the block"

    def test_no_run_fk_or_changed_deletion_semantics(self, empty_database) -> None:
        """The claim table gains no foreign key to the Run spine: its deletion
        semantics stay its own (TTL purge + explicit release), unchanged by the
        forward representation."""
        assert _alembic("upgrade", "head").returncode == 0
        constraints = _query(
            """
            select contype, conname
            from pg_constraint
            where conrelid = 'task_idempotency'::regclass
            """
        )
        assert all(contype != "f" for contype, _name in constraints), constraints
        assert _query(
            """
            select count(*) from pg_constraint
            where confrelid = 'task_idempotency'::regclass and contype = 'f'
            """
        ) == [(0,)], "another table now references the claim table"
        assert sorted(name for contype, name in constraints if contype == "p") == [
            "pk_task_idempotency"
        ]
        assert _query(
            "select count(*) from pg_indexes where tablename = 'task_idempotency' "
            "and indexname = 'ix_task_idempotency_expires'"
        ) == [(1,)]


class TestTheV2Check:
    def test_each_required_v2_field_null_is_rejected(self, empty_database) -> None:
        """NULL injected into each nullable-but-required v2 field, one at a
        time. PostgreSQL CHECK passes UNKNOWN, so every field needs its own
        explicit IS NOT NULL — this is the test that proves each one exists."""
        assert _alembic("upgrade", "head").returncode == 0
        import psycopg

        for field in V2_REQUIRED_FIELDS:
            row = _valid_v2_row(**{field: None})
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_v2(row)
            # The row never landed: the next iteration inserts the same key.
            assert _query("select count(*) from task_idempotency") == [(0,)], field

    def test_v2_constraints_reject_partial_identity_and_binding(self, empty_database) -> None:
        """Every non-NULL way a v2 row can be incomplete is refused: bad hex,
        nil identities, blank ids/action, a half-bound pair, a binding that
        points at someone else's receipt, an unacknowledged ack, and a
        non-positive window."""
        assert _alembic("upgrade", "head").returncode == 0
        import psycopg

        refusals: dict[str, dict[str, Any]] = {
            "uppercase generation": {"generation_id": GENERATION_ID.upper()},
            "short generation": {"generation_id": "abc123"},
            "nil generation": {"generation_id": NIL_HEX},
            "non-hex owner token": {"claim_token": "not-hex-at-all"},
            "nil owner token": {"claim_token": NIL_HEX},
            "blank workspace": {"workspace_id": "   "},
            "blank project": {"project_id": ""},
            "blank origin principal": {"origin_principal_id": " "},
            "blank actor principal": {"actor_principal_id": ""},
            "blank action": {"action": "  "},
            "blank receipt": {"receipt_id": ""},
            "zero window": {"expires_at": 1000},
            "negative window": {"expires_at": 999},
            "task bound without run": {"task_id": "receipt-1"},
            "run bound without task": {"run_id": "run-1"},
            "binding to another receipt": {
                "task_id": "someone-elses-task",
                "run_id": "run-1",
            },
            "acknowledged while unbound": {"acknowledged_at": 3000},
        }
        for label, overrides in refusals.items():
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_v2(_valid_v2_row(**overrides))
            assert _query("select count(*) from task_idempotency") == [(0,)], label

    def test_valid_v2_generations_are_admitted(self, empty_database) -> None:
        """The positive half: a complete unbound generation, and the same one
        bound to its own receipt and acknowledged, both land."""
        assert _alembic("upgrade", "head").returncode == 0
        _insert_v2(_valid_v2_row())
        assert _query(
            "select format_version, task_id, run_id, acknowledged_at "
            "from task_idempotency where scope_key = 'v2-claim'"
        ) == [(2, None, None, None)]

        _execute(
            """
            update task_idempotency
            set task_id = receipt_id, run_id = 'run-1', acknowledged_at = 3000
            where scope_key = 'v2-claim'
            """
        )
        assert _query(
            "select task_id, run_id, acknowledged_at from task_idempotency "
            "where scope_key = 'v2-claim'"
        ) == [("receipt-1", "run-1", 3000)]

    def test_format_v1_rows_stay_unconstrained(self, empty_database) -> None:
        """Original format-v1 rows are admitted exactly as they stand — the v2
        CHECK is conditional, so legacy shapes (including odd ones the shipped
        writers never produced) pass unmodified."""
        assert _alembic("upgrade", "head").returncode == 0
        _execute(
            """
            insert into task_idempotency
                (scope_key, format_version, generation_id, claim_token,
                 workspace_id, project_id, origin_principal_id,
                 actor_principal_id, action, receipt_id, receipt_snapshot,
                 provenance_snapshot, fingerprint, request, task_id, run_id,
                 created_at, expires_at, lease_expires_at, acknowledged_at)
            values ('legacy-odd', 1, 'not-even-hex', NULL,
                    '', '', '', '', '', '', NULL,
                    NULL, 'fp', 'req', NULL, NULL,
                    500, 400, 450, 9999)
            """
        )
        assert _query(
            "select format_version, expires_at < created_at, acknowledged_at "
            "from task_idempotency where scope_key = 'legacy-odd'"
        ) == [(1, True, 9999)]


class TestTheDowngrade:
    def test_rollback_cannot_silently_discard_live_v2_identity(self, empty_database) -> None:
        """Downgrading while a live generation exists refuses BEFORE any
        change: the stamp, the columns and the row itself all survive the
        failed attempt untouched."""
        assert _alembic("upgrade", "head").returncode == 0
        _insert_v2(_valid_v2_row(task_id="receipt-1", run_id="run-1", acknowledged_at=3000))
        _execute(_shipped_row_sql("legacy-claim", complete=True))
        before = _query("select * from task_idempotency order by scope_key")

        result = _alembic("downgrade", "052")

        assert result.returncode != 0, "the downgrade discarded live v2 identity"
        assert "format_version" in result.stderr + result.stdout
        # A multi-revision `alembic downgrade` is one transaction: the refusal
        # partway through rolls the whole attempt back, so the stamp never
        # moves off whatever head it started from. The assertion tracks the
        # head, not a fixed literal — every develop collision re-parents the
        # chain tip, and the invariant under test is that the refused
        # downgrade leaves the stamp AT HEAD. Develop's quota door
        # (#1196/#718) landed on `055` as `043_invocation_quota_door`;
        # develop's trunk then landed `056_user_model_facts` (#1047) on that
        # quota-door parent with #863's planner-stability revision on top as
        # `057`, and the backlog authority-cutover pair (#98/#102) re-parents
        # past each incoming develop tip in turn — `058`/`059`, then `059`/
        # `060` once develop's `058_learning_validation_provenance` claimed
        # `058`. The literal has drifted once per landing, so the head is now
        # read from the same version files the upgrade above ran.
        assert _stamped_version() == _chain_head()
        assert _query("select * from task_idempotency order by scope_key") == before
        assert "generation_id" in _v2_columns()

    def test_legacy_only_data_downgrades_and_upgrades_again(self, empty_database) -> None:
        """With only empty/legacy data the downgrade drops the v2 columns and
        the CHECK, keeps every original column and row, retains the optional
        legacy claim_token evidence — and the upgrade accepts exactly that
        safe-downgrade shape without rewriting the survivor."""
        assert _alembic("upgrade", "head").returncode == 0
        _execute(_shipped_row_sql("survivor", complete=False))
        before = _shipped_rows()

        assert _alembic("downgrade", "052").returncode == 0

        columns = _v2_columns()
        retained = {
            "scope_key",
            "fingerprint",
            "request",
            "task_id",
            "run_id",
            "created_at",
            "expires_at",
            "lease_expires_at",
            "claim_token",
        }
        assert set(columns) == retained
        assert columns["claim_token"] == {"type": "text", "nullable": "YES", "default": None}
        assert _query(
            "select count(*) from pg_constraint where conname = "
            "'ck_task_idempotency_v2_identity' and conrelid = "
            "'task_idempotency'::regclass"
        ) == [(0,)]
        assert _shipped_rows() == before

        # The safe-downgrade shape re-upgrades: claim_token is recognized as
        # retained evidence, not re-created or validated for nullability.
        assert _alembic("upgrade", "head").returncode == 0
        assert _shipped_rows() == before
        assert _query(
            "select format_version from task_idempotency where scope_key = 'survivor'"
        ) == [(1,)]
