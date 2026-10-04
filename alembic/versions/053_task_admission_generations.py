"""Forward admission-generation representation on task_idempotency (#1892).

A staged, reviewable representation leaf on the L41/#1325 integration line —
not a writer. Nothing here activates a new admission path, changes a queue,
touches startup DDL, or alters Run policy or claim mutation: the shipped
writers keep inserting their named column list, and every column this
revision adds is nullable (or carries the legacy default ``1``), so the
pre-existing INSERTs keep working unchanged. The open product choices remain
open in #1845; this revision only gives them a durable shape to land on.

What it adds to the claim table, without touching any existing column:

- ``format_version SMALLINT NOT NULL DEFAULT 1`` — existing rows stay format
  v1 by default, and the v2 CHECK below is conditional, so every legacy row
  is admitted exactly as it stands.
- ``generation_id`` — the immutable admission generation identity (lowercase
  32-hex, non-nil) a v2 writer mints once per logical submission.
- ``claim_token TEXT NULL`` — owner-token storage. On schemas where an
  earlier integration branch already shipped this column NOT NULL (#1325's
  reconciliation of 038), it is retained as-is: every v2 insert supplies it,
  so the NOT NULL costs nothing. Where it is absent, it is added nullable.
- The fixed canonical scope/action metadata (``workspace_id``, ``project_id``,
  ``origin_principal_id``, ``actor_principal_id``, ``action``), the proposed
  ``receipt_id`` and its TEXT ``receipt_snapshot`` / ``provenance_snapshot``
  evidence, and ``acknowledged_at`` (microseconds, like its siblings) — NULL
  until a bound claim is acknowledged.
- ``task_id`` / ``run_id`` keep their shipped meaning as the binding pair:
  both NULL while the claim is pending, both present when bound, and a bound
  v2 claim must bind ``task_id`` to its own proposed ``receipt_id``.

The v2 CHECK (``ck_task_idempotency_v2_identity``) rejects incomplete v2 rows
and leaves format-v1 rows completely unconstrained. PostgreSQL CHECK treats
NULL as UNKNOWN and UNKNOWN as pass, so every nullable-but-required v2 field
is pinned with an explicit ``IS NOT NULL`` before it is compared — a bare
``generation_id ~ '...'`` would happily admit a NULL generation. The window
is represented as ``expires_at > created_at`` only: the exact 24-hour
production TTL is the writer's configured policy (#1851 permits positive
configured windows, including short test windows), not a schema constant.

Reconciliation contract, per case:

- A fresh chain builds the baseline in 038 and this revision extends it.
- An already-migrated database keeps every preexisting claim byte-for-byte in
  its original columns; ADD COLUMN with the v1 default is the whole data
  story. A database carrying the known #1325 claim shape (``claim_token``,
  ``completed_at``) keeps those columns too — they are optional legacy
  evidence this revision recognizes and retains, never rewrites.
- A database that already carries this revision's own complete forward shape
  is adopted unchanged — after re-validating types, defaults, nullability,
  the primary key, the expiry index, and the v2 CHECK — so stamp-back and
  re-upgrade stays the repair path (the chain-level adoption test drives
  exactly that walk). Re-adoption rewrites nothing: populated v2 rows are
  preserved byte-for-byte.
- Anything else — a column with the wrong type, a missing or misplaced
  primary key, a lost expiry index, a constraint squatting on this
  revision's CHECK name without the v2 contract — refuses loudly rather than
  stamping a false head. In particular a runtime-provisioned table with a
  PRE-038 history never reaches this revision at all: the shipped 038
  encounters it first and the chain stops there, which is the intended
  block. Reconciling such a table is a reviewed operator action, not
  something this revision papers over by editing history.
- The downgrade refuses — before making any change — while any non-legacy
  row exists (``format_version`` other than 1, v2 or unknown future
  versions): an old writer must not be handed a table that still holds
  identities it cannot read. With only empty/legacy data it drops the v2
  columns and the CHECK, keeps every original column and row, and retains
  the optional legacy ``claim_token`` / ``completed_at`` columns: their
  pre-migration origin is not provable at downgrade time, so they stay, and
  the upgrade above recognizes exactly that safe-downgrade shape.

Numbered 053 on the develop base whose chain tip is ``052_learning_stage_
ladder``. The #1855 branch currently holds its own ``052_canonical_goals``;
per this chain's documented collision convention (see 052 and 036), whichever
revision lands second re-parents onto the merged tip. No duplicate ids.

Revision ID: 053
Revises: 052
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

#: The columns shipped 038 owns. Types are spelled as the uppercase DDL names
#: reflection hands back on live PostgreSQL (``TEXT``/``BIGINT``), so the
#: validation below compares what the server built, not what a dialect class
#: compiled. ``(name, type, nullable)``.
_BASELINE_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("scope_key", "TEXT", False),
    ("fingerprint", "TEXT", False),
    ("request", "TEXT", False),
    ("task_id", "TEXT", True),
    ("run_id", "TEXT", True),
    ("created_at", "BIGINT", False),
    ("expires_at", "BIGINT", False),
    ("lease_expires_at", "BIGINT", False),
)

#: The columns this revision adds. All nullable except ``format_version``,
#: which carries the legacy default so existing rows stay format v1.
#: ``claim_token`` is the owner-token storage: added nullable on baseline
#: schemas, but where an earlier integration shape (#1325's reconciled 038)
#: already shipped it NOT NULL it is retained as found — every v2 insert
#: supplies it, so the NOT NULL costs nothing. Its nullability is therefore
#: not pinned (see _NULLABILITY_UNPINNED).
#
#: Deliberately a plain module-level assignment, not an annotated one: the
#: retention-inventory scan (``check-durable-table-inventory``) resolves the
#: loop-bound names of ``for name, ddl_type, nullable in _FORWARD_COLUMNS``
#: only from unannotated module tuples, and an unresolved column name in an
#: ``op.add_column`` is silently unverifiable. Keeping the literal shape here
#: means a future ``run_id`` row in this tuple would be reported by that
#: scan, not skipped — the same contract every other tuple-driven migration
#: in this chain honors.
_FORWARD_COLUMNS = (
    ("format_version", "SMALLINT", False),
    ("generation_id", "TEXT", True),
    ("claim_token", "TEXT", True),
    ("workspace_id", "TEXT", True),
    ("project_id", "TEXT", True),
    ("origin_principal_id", "TEXT", True),
    ("actor_principal_id", "TEXT", True),
    ("action", "TEXT", True),
    ("receipt_id", "TEXT", True),
    ("receipt_snapshot", "TEXT", True),
    ("provenance_snapshot", "TEXT", True),
    ("acknowledged_at", "BIGINT", True),
)

#: Forward columns whose nullability is not pinned when they are already
#: standing: the L41 NOT NULL ``claim_token`` and the safe-downgrade nullable
#: one are both the claim table.
_NULLABILITY_UNPINNED = frozenset({"claim_token"})

#: Columns a known earlier integration shape (#1325's reconciled 038) shipped
#: that the develop baseline does not and this revision does not add. This
#: revision recognizes them, keeps them exactly as found (their nullability
#: is not pinned: the shipped NOT NULL defaulted ``completed_at`` is fine),
#: and — importantly — the downgrade retains them, because whether they
#: predate this revision is not provable at downgrade time. Retention is the
#: safe direction, and the upgrade accepts the resulting shape.
_OPTIONAL_LEGACY_COLUMNS: tuple[tuple[str, str], ...] = (("completed_at", "BIGINT"),)

#: Forward columns the downgrade does NOT drop, for the same unprovable-origin
#: reason: ``claim_token`` may have shipped with the earlier integration shape,
#: and a baseline table cannot prove this revision added it.
_DOWNGRADE_RETAINED = frozenset({"claim_token"})

_CHECK_NAME = "ck_task_idempotency_v2_identity"

#: Tokens the v2 CHECK must mention. A constraint squatting on this name
#: without them is not the v2 contract, and adopting it would stamp a false
#: head over a table the v2 decoder cannot trust.
_CHECK_REQUIRED_TOKENS = (
    "format_version",
    "generation_id",
    "claim_token",
    "workspace_id",
    "receipt_id",
    "acknowledged_at",
)

_EXPIRY_INDEX = "ix_task_idempotency_expires"

#: DDL type names (exactly what ``_validate_forward_columns`` compares against
#: reflection) mapped to the SQLAlchemy types ``op.add_column`` compiles back
#: to the same DDL on PostgreSQL.
_SA_TYPES: dict[str, type[sa.types.TypeEngine]] = {
    "TEXT": sa.Text,
    "SMALLINT": sa.SmallInteger,
    "BIGINT": sa.BigInteger,
}

_V2_CHECK_SQL = f"""
    ALTER TABLE task_idempotency ADD CONSTRAINT {_CHECK_NAME} CHECK (
        format_version <> 2
        OR (
            generation_id IS NOT NULL
            AND generation_id ~ '^[0-9a-f]{{32}}$'
            AND generation_id <> '00000000000000000000000000000000'
            AND claim_token IS NOT NULL
            AND claim_token ~ '^[0-9a-f]{{32}}$'
            AND claim_token <> '00000000000000000000000000000000'
            AND workspace_id IS NOT NULL AND btrim(workspace_id) <> ''
            AND project_id IS NOT NULL AND btrim(project_id) <> ''
            AND origin_principal_id IS NOT NULL AND btrim(origin_principal_id) <> ''
            AND actor_principal_id IS NOT NULL AND btrim(actor_principal_id) <> ''
            AND action IS NOT NULL AND btrim(action) <> ''
            AND receipt_id IS NOT NULL AND btrim(receipt_id) <> ''
            AND receipt_snapshot IS NOT NULL
            AND provenance_snapshot IS NOT NULL
            AND expires_at > created_at
            AND (
                (task_id IS NULL AND run_id IS NULL)
                OR (task_id IS NOT NULL AND run_id IS NOT NULL AND task_id = receipt_id)
            )
            AND (acknowledged_at IS NULL OR (task_id IS NOT NULL AND run_id IS NOT NULL))
        )
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("task_idempotency"):
        # Unreachable through the linear chain (038 builds the table), so
        # meeting this revision without it means somebody is stamping head
        # over a database the chain never touched. Refuse, loudly.
        raise RuntimeError(
            "task_idempotency does not exist but revision 053 assumes it; "
            "the migration chain cannot stamp a forward admission-generation "
            "shape over a database that never ran 038"
        )
    columns = _column_map(inspector)
    _validate_baseline_columns(columns)
    _validate_optional_legacy_columns(columns)
    _validate_forward_columns(columns)
    _validate_primary_key(inspector)
    _validate_expiry_index(inspector)
    _add_forward_columns(columns)
    _add_v2_check(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("task_idempotency"):
        return
    columns = _column_map(inspector)
    if "format_version" not in columns:
        # The forward shape was never applied (e.g. the optional legacy
        # columns survive from an earlier downgrade); nothing of this
        # revision's is standing.
        return
    # Refuse BEFORE any DDL: a live v2 generation (or an unknown future
    # format) must not be silently discarded into a shape no old writer can
    # read. Order matters as much as the refusal — on a non-transactional DDL
    # path a late check would still have dropped columns by the time it fired.
    non_legacy = bind.execute(
        sa.text("SELECT count(*) FROM task_idempotency WHERE format_version <> 1")
    ).scalar_one()
    if non_legacy:
        raise RuntimeError(
            f"task_idempotency holds {non_legacy} row(s) with format_version <> 1; "
            "downgrading would discard live admission generations that an "
            "earlier writer cannot read. Clear or revert the non-legacy rows "
            "first (a reviewed operator action), then downgrade."
        )
    bind.execute(sa.text(f"ALTER TABLE task_idempotency DROP CONSTRAINT IF EXISTS {_CHECK_NAME}"))
    for name, _type, _nullable in _FORWARD_COLUMNS:
        if name in _DOWNGRADE_RETAINED or name not in columns:
            continue
        op.drop_column("task_idempotency", name)
    # Deliberately retained: claim_token (in _DOWNGRADE_RETAINED) and the
    # optional legacy completed_at. Their origin is not provable here (this
    # revision adds claim_token on baseline schemas but meets it pre-existing
    # and NOT NULL on the #1325 shape), and dropping evidence on a guess is
    # exactly the failure this downgrade exists to avoid. The upgrade above
    # accepts the shape this leaves behind.


def _column_map(inspector: sa.Inspector) -> dict[str, dict[str, object]]:
    return {col["name"]: col for col in inspector.get_columns("task_idempotency")}


def _reflected_type(column: dict[str, object]) -> str:
    return str(column["type"]).upper()


def _validate_baseline_columns(columns: dict[str, dict[str, object]]) -> None:
    malformed = []
    for name, expected_type, expected_nullable in _BASELINE_COLUMNS:
        column = columns.get(name)
        if column is None:
            malformed.append(
                f"missing {name}: baseline column the claim store cannot read or write without"
            )
            continue
        if _reflected_type(column) != expected_type:
            malformed.append(f"{name} has type {column['type']!s}, expected {expected_type}")
        if column["nullable"] is not expected_nullable:
            malformed.append(
                f"{name} nullable={column['nullable']!r}, expected {expected_nullable!r}"
            )
    if malformed:
        raise RuntimeError(_malformed_message("baseline", malformed))


def _validate_optional_legacy_columns(columns: dict[str, dict[str, object]]) -> None:
    """A known #1325 claim shape carries these; only their TYPE is pinned.

    Nullability is deliberately unchecked: the shipped ``claim_token`` is NOT
    NULL, a safe downgrade leaves it nullable, and both are the claim table.
    Absent is equally fine — the baseline never had them.
    """
    malformed = []
    for name, expected_type in _OPTIONAL_LEGACY_COLUMNS:
        column = columns.get(name)
        if column is None:
            continue
        if _reflected_type(column) != expected_type:
            malformed.append(f"{name} has type {column['type']!s}, expected {expected_type}")
    if malformed:
        raise RuntimeError(_malformed_message("optional legacy", malformed))


def _validate_forward_columns(columns: dict[str, dict[str, object]]) -> None:
    """Any forward column already standing must be exactly this revision's.

    Partial presence is normal (a half-applied upgrade, the safe-downgrade
    shape's retained ``claim_token``, or the L41 NOT NULL one); wrong types
    and unpinned-nullability violations are not adoptable.
    """
    malformed = []
    for name, expected_type, expected_nullable in _FORWARD_COLUMNS:
        column = columns.get(name)
        if column is None:
            continue
        if _reflected_type(column) != expected_type:
            malformed.append(f"{name} has type {column['type']!s}, expected {expected_type}")
        if name not in _NULLABILITY_UNPINNED and column["nullable"] is not expected_nullable:
            malformed.append(
                f"{name} nullable={column['nullable']!r}, expected {expected_nullable!r}"
            )
    version = columns.get("format_version")
    if version is not None:
        # SQLAlchemy's PostgreSQL reflection hands the server default back as
        # ``default`` (a plain '1'); read both spellings so the check does not
        # depend on which key this dialect filled.
        default = version.get("server_default") or version.get("default")
        default_text = str(default).strip().strip("'").strip()
        if default_text != "1":
            malformed.append(f"format_version has default {default!r}, expected 1")
    if malformed:
        raise RuntimeError(_malformed_message("forward", malformed))


def _validate_primary_key(inspector: sa.Inspector) -> None:
    pk = inspector.get_pk_constraint("task_idempotency")
    if pk.get("constrained_columns") != ["scope_key"]:
        raise RuntimeError(
            "task_idempotency's primary key is "
            f"{pk.get('constrained_columns')!r}, expected ['scope_key']: the "
            "key IS the claim, and this revision will not stamp a forward "
            "generation shape over a table that cannot enforce claim identity"
        )


def _validate_expiry_index(inspector: sa.Inspector) -> None:
    indexes = {ix["name"]: ix for ix in inspector.get_indexes("task_idempotency")}
    expires_index = indexes.get(_EXPIRY_INDEX)
    if expires_index is None:
        raise RuntimeError(
            f"task_idempotency is missing {_EXPIRY_INDEX}: the purge query's "
            "scan bound must exist before this revision stamps forward "
            "generations onto the claim table"
        )
    if expires_index.get("column_names") != ["expires_at"] or expires_index.get("unique", False):
        raise RuntimeError(
            f"task_idempotency has an incompatible {_EXPIRY_INDEX} definition: {expires_index!r}"
        )


def _add_forward_columns(columns: dict[str, dict[str, object]]) -> None:
    for name, ddl_type, nullable in _FORWARD_COLUMNS:
        if name in columns:
            continue  # validated above; adoption adds nothing
        op.add_column(
            "task_idempotency",
            sa.Column(
                name,
                _SA_TYPES[ddl_type](),
                nullable=nullable,
                server_default=sa.text("1") if name == "format_version" else None,
            ),
        )


def _add_v2_check(bind: sa.Connection) -> None:
    existing = bind.execute(
        sa.text(
            "SELECT contype, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = :name AND conrelid = 'task_idempotency'::regclass"
        ),
        {"name": _CHECK_NAME},
    ).first()
    if existing is not None:
        contype, definition = str(existing[0]), str(existing[1])
        missing = [token for token in _CHECK_REQUIRED_TOKENS if token not in definition]
        if contype != "c" or missing:
            raise RuntimeError(
                f"a {_CHECK_NAME} constraint already exists on task_idempotency "
                f"(type {contype!r}) but does not carry the v2 identity contract "
                f"(missing tokens: {missing}); refusing to adopt it as this "
                "revision's CHECK"
            )
        return
    bind.execute(sa.text(_V2_CHECK_SQL))


def _malformed_message(kind: str, malformed: list[str]) -> str:
    return (
        f"task_idempotency exists with an incompatible {kind} shape; refusing "
        f"to stamp revision 053 over it: " + "; ".join(malformed)
    )
