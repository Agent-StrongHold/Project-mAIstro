"""The Canvas store's own tables join the chain (#286).

`PgCanvasStore` (maistro_canvas.canvas.store) reads and writes `canvases`,
`layers`, `generation_jobs`, `composite_records` and `canvas_blobs`, and until
now no migration in this repository created any of them: migration 002 called
them "created elsewhere", the book-maker POC chain altered `generation_jobs`
without ever creating it, and the only DDL lived in a test. A database migrated
to head therefore could not run the Canvas store at all.

Live deployments did create these tables, by hand or from the POC, so this
adopts rather than assumes an empty database: every table is `CREATE TABLE IF
NOT EXISTS` holding only its primary key, and every other column is then `ADD
COLUMN IF NOT EXISTS` from the one list below. A fresh table and an adopted one
are built from the same definitions; an adopted table missing (say) the
SPEC-203 lease columns gains them, and one already at this shape is untouched.
A NOT NULL column with no default cannot be added to a populated table, so a
live table missing an identity column such as `canvases.name` or
`layers.canvas_id` fails the upgrade loudly rather than being given an invented
value. An adopted table keeps the constraints it was created with, except that
`layers` gains the unique constraint below when it has none over
`(canvas_id, z_index)`.

`UNIQUE (canvas_id, z_index)` is `DEFERRABLE INITIALLY DEFERRED`. PostgreSQL
checks a non-deferrable unique constraint row by row, so the store's
`reorder_layers` (one UPDATE per layer) and `delete_layer` (shift every higher
layer down by one) would collide on an intermediate state that is never
committed. Deferred, the constraint still guards the committed order, which is
what the store's docstring relies on it for.

`ix_generation_jobs_pending` is the POC chain's 003 index under the same name,
so a database that already ran it is left as it is.

Downgrade drops all five tables, including rows an adopted table held before
this migration ran.

Revision ID: 044
Revises: 042
Create Date: 2026-09-26
"""

from __future__ import annotations

from alembic import op

revision = "044"
down_revision = "042"
branch_labels = None
depends_on = None

_NOW = "TIMESTAMPTZ NOT NULL DEFAULT now()"

_CANVAS_COLUMNS = (
    ("name", "TEXT NOT NULL"),
    ("width", "INTEGER NOT NULL"),
    ("height", "INTEGER NOT NULL"),
    ("background_color", "TEXT NOT NULL DEFAULT '#FFFFFF'"),
    ("org_id", "TEXT NOT NULL DEFAULT ''"),
    ("layer_count", "INTEGER NOT NULL DEFAULT 0"),
    ("archived_at", "TIMESTAMPTZ"),
    ("created_at", _NOW),
    ("updated_at", _NOW),
)
_LAYER_COLUMNS = (
    ("canvas_id", "TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE"),
    ("name", "TEXT NOT NULL"),
    ("layer_type", "TEXT NOT NULL DEFAULT 'background'"),
    ("z_index", "INTEGER NOT NULL DEFAULT 0"),
    ("x", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("y", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("scale", "DOUBLE PRECISION NOT NULL DEFAULT 1"),
    ("rotation", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("opacity", "DOUBLE PRECISION NOT NULL DEFAULT 1"),
    ("blend_mode", "TEXT NOT NULL DEFAULT 'normal'"),
    ("visible", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("locked", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("image_path", "TEXT"),
    ("prompt", "TEXT"),
    ("negative_prompt", "TEXT"),
    ("model_id", "TEXT"),
    ("tier", "TEXT DEFAULT 'draft'"),
    ("generation_seed", "INTEGER"),
    ("text_config", "JSONB"),
    ("created_at", _NOW),
    ("updated_at", _NOW),
)
_JOB_COLUMNS = (
    ("layer_id", "TEXT NOT NULL REFERENCES layers(id) ON DELETE CASCADE"),
    ("canvas_id", "TEXT NOT NULL"),
    ("action", "TEXT NOT NULL DEFAULT 'generate'"),
    ("status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("model_id", "TEXT NOT NULL DEFAULT ''"),
    ("prompt", "TEXT NOT NULL DEFAULT ''"),
    ("params", "JSONB NOT NULL DEFAULT '{}'"),
    ("result_paths", "JSONB NOT NULL DEFAULT '[]'"),
    ("selected_index", "INTEGER"),
    ("error_message", "TEXT"),
    ("started_at", "TIMESTAMPTZ"),
    ("completed_at", "TIMESTAMPTZ"),
    ("created_at", _NOW),
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
    ("leased_by", "TEXT"),
    ("lease_expires_at", "TIMESTAMPTZ"),
)
_COMPOSITE_COLUMNS = (
    ("canvas_id", "TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE"),
    ("image_bytes", "BYTEA NOT NULL"),
    ("width", "INTEGER NOT NULL"),
    ("height", "INTEGER NOT NULL"),
    ("layer_snapshot", "JSONB NOT NULL DEFAULT '[]'"),
    ("created_at", _NOW),
)
_BLOB_COLUMNS = (
    ("data", "BYTEA NOT NULL"),
    ("format", "TEXT NOT NULL"),
    ("metadata", "JSONB NOT NULL DEFAULT '{}'"),
    ("created_at", _NOW),
)

_TABLES = ("canvases", "layers", "generation_jobs", "composite_records", "canvas_blobs")


def _add_columns(table: str, columns: tuple[tuple[str, str], ...]) -> None:
    for name, spec in columns:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {spec}")


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS canvases (id TEXT PRIMARY KEY)")
    _add_columns("canvases", _CANVAS_COLUMNS)
    op.execute("CREATE TABLE IF NOT EXISTS layers (id TEXT PRIMARY KEY)")
    _add_columns("layers", _LAYER_COLUMNS)
    op.execute("CREATE TABLE IF NOT EXISTS generation_jobs (id TEXT PRIMARY KEY)")
    _add_columns("generation_jobs", _JOB_COLUMNS)
    op.execute("CREATE TABLE IF NOT EXISTS composite_records (id TEXT PRIMARY KEY)")
    _add_columns("composite_records", _COMPOSITE_COLUMNS)
    op.execute("CREATE TABLE IF NOT EXISTS canvas_blobs (id TEXT PRIMARY KEY)")
    _add_columns("canvas_blobs", _BLOB_COLUMNS)

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint c
                WHERE c.conrelid = 'layers'::regclass
                  AND c.contype = 'u'
                  AND ARRAY(
                        SELECT a.attname::text FROM pg_attribute a
                        WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                        ORDER BY a.attname
                      ) = ARRAY['canvas_id', 'z_index']
            ) THEN
                ALTER TABLE layers ADD CONSTRAINT uq_layers_canvas_z
                    UNIQUE (canvas_id, z_index) DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_generation_jobs_pending"
        " ON generation_jobs (created_at) WHERE status = 'pending'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_generation_jobs_layer ON generation_jobs (layer_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_composite_records_canvas"
        " ON composite_records (canvas_id, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_canvases_org ON canvases (org_id, updated_at)")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
