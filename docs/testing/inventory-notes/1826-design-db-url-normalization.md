---
inventory-delta:
  packages/hive-conductor/backend/tests: +23
---
# 1826-design-db-url-normalization

Issue #1826 — normalize the installed Design database URL before creating its
async SQLAlchemy engine.

The fix routes `services.design_service._get_async_engine` through the shared
config contract (`resolve_database_url` + `to_async_url`, the same pair
`maistro.memory.store.get_engine` runs) instead of a raw `DATABASE_URL` read,
and makes a configured-but-broken URL raise `DesignStoreConfigurationError`
with a sanitized cause instead of degrading into the same `None` — and the
same "no DATABASE_URL configured" startup line — as the supported no-database
mode. `DesignServiceStatus` carries the new `store_cause`, and
`routes.design._require_store` answers project routes with it.

## What the 23 node IDs cover

`test_design_store_wiring.py` (18, hermetic — `create_async_engine` selects a
dialect from the URL alone, so no server is needed):

- 2: the exact Compose spelling (`postgresql://maistro:…@postgres:5432/maistro`)
  produces an asyncpg-backed engine and a session factory at the service's own
  boundary. This is the regression the issue names: under the old code the
  same call raised `ModuleNotFoundError` for psycopg2 and was swallowed into
  `None` (asserted against the pre-fix body verbatim).
- 4 (parametrized): every spelling the canonical normalizer accepts —
  `postgresql://`, `postgres://`, `postgresql+asyncpg://`,
  `postgresql+psycopg://` — arrives as the same asyncpg engine with
  credentials, host, port, database and query data unchanged.
- 3: an absent URL stays a supported, explicit mode — engine/factory `None`,
  startup `ready` with `store_cause is None`, route answers "no database URL
  configured".
- 8: a configured URL that cannot build an engine (forced
  `ModuleNotFoundError`, a real malformed-URL `ValueError` from
  SQLAlchemy, and a netloc-less spelling the shared redactor cannot parse)
  raises `DesignStoreConfigurationError`, startup degrades with
  the recorded sanitized cause, the status dict carries it, and the route
  answers with the actual failure — never "not set", never the password
  (AC-7: the cause names the exception type against a redacted URL and never
  interpolates `str(exc)`). The eighth pins the route's other unavailable
  form: an accessor seam that yields `None` while a cause is recorded must
  answer with that cause too, never the no-database message (repair round:
  the diff-coverage gate named the seam's cause leg unexecuted; the test
  was shown to fail when that leg is reverted to the absence answer).
- 2: resolution is persistence-scoped too (salvage review) — a `DB_*` value
  pydantic rejects (`DB_PORT=notaport`) raises `DesignStoreConfigurationError`
  from the same boundary, naming the exception type and never the environment
  value; startup degrades *only* the store, where an uncaught
  `ValidationError` used to mark the whole service unready.

`test_design_supported_path.py` (4, PostgreSQL — skip without
`MAISTRO_TEST_PG_DSN`; `MAISTRO_REQUIRE_PG_LEGS` makes the skip a failure,
same contract as the Canvas supported-path module): a clean database migrated
by the authoritative root chain only, `DATABASE_URL` set in the Compose
spelling, the real `start_design_service` composition, then create/read/list
through the real routes with org scope rules, and a stop/start restart reading
the persisted project back through a fresh store.
