---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +9
---
# 82-backlog-server-wiring

This delta belongs to the #82/#98 server-wiring slice that closes the
reachability disposition named in `82-backlog-work-source.md`: the
`maistro.backlog` work-source is no longer a built-but-unwired library
surface — `maistro_server` now serves it over HTTP, which is what makes all
five original modules (plus the new `maistro.backlog.wiring`) reachable from a
real process entry point.

- **+6 core nodes** (`packages/maistro-core/tests/backlog/test_backlog_wiring.py`):
  `wire_backlog_store` selects the Project store's backend — PostgreSQL gets
  the durable `PgBacklogStore` over Alembic revision 059's tables, SQLite gets
  the durable twin on its own connection with the schema ensured (one item
  round-trips with its `created` event), anything else gets the in-memory
  reference — and a backend that arrives without its driver handle is a
  `ConfigError`, not a silent demotion to in-memory.
- **+9 server nodes** (`packages/maistro-server/tests/api/test_backlog_items_api.py`):
  the `/v1/workspaces/{id}/backlog-items` routes over the canonical store —
  member create/list/get/edit with filters, tri-state PATCH semantics
  (field absent = no opinion, explicit null = clear, via `model_fields_set`),
  409 on a stale `expected_version` carrying the current version, closure
  evidence required at terminal outcomes (422 otherwise), reopen of live or
  stale items refused, the atomic claim/lease lifecycle (exclusive claim,
  extend, release, re-claim; a claim never bumps the item version), ordered
  attributed events, and the fail-closed 404 discipline: a member asking for a
  foreign item gets the same answer as an unknown one, an outsider is stopped
  at the Workspace boundary, and a deployment with no store selected is a 503.

No existing test moved or was renamed; the counts are purely additive.
