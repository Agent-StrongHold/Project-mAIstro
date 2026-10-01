"""The canvas schema as migrations 044 + 048 declare it (test-local DDL).

The durable-table gate and ``test_canvas_store_migration`` keep the root
alembic chain honest; this DDL is only for suites that build a throwaway
schema directly (scope conformance, job-store contract) instead of driving
``alembic``. It must state the same columns the store's SQL touches — a new
store column lands here in the same change as the SQL that reads it.
"""

from __future__ import annotations

CANVAS_SCHEMA_DDL = """
CREATE TABLE canvases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    background_color TEXT NOT NULL DEFAULT '#FFFFFF',
    org_id TEXT NOT NULL DEFAULT '',
    layer_count INTEGER NOT NULL DEFAULT 0,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE layers (
    id TEXT PRIMARY KEY,
    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    layer_type TEXT NOT NULL DEFAULT 'background',
    z_index INTEGER NOT NULL DEFAULT 0,
    x DOUBLE PRECISION NOT NULL DEFAULT 0,
    y DOUBLE PRECISION NOT NULL DEFAULT 0,
    scale DOUBLE PRECISION NOT NULL DEFAULT 1,
    rotation DOUBLE PRECISION NOT NULL DEFAULT 0,
    opacity DOUBLE PRECISION NOT NULL DEFAULT 1,
    blend_mode TEXT NOT NULL DEFAULT 'normal',
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    image_path TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    model_id TEXT,
    tier TEXT DEFAULT 'draft',
    generation_seed INTEGER,
    text_config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canvas_id, z_index)
);
CREATE TABLE generation_jobs (
    id TEXT PRIMARY KEY,
    layer_id TEXT NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
    canvas_id TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'generate',
    status TEXT NOT NULL DEFAULT 'pending',
    model_id TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    params JSONB NOT NULL DEFAULT '{}',
    result_paths JSONB NOT NULL DEFAULT '[]',
    selected_index INTEGER,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    leased_by TEXT,
    lease_expires_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ
);
CREATE TABLE composite_records (
    id TEXT PRIMARY KEY,
    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    image_bytes BYTEA NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    layer_snapshot JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
