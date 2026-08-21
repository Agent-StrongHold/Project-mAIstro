---
id: SPEC-062226-fb23
title: "ConfigStore: DB table model, caching, CLI commands, and admin API endpoints (ADR-078)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-22
substrate:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-078
  - maistro-engine#ADR-062226-674b
implements:
  - maistro-engine#ADR-078
  - maistro-engine#ADR-062226-674b
related:
  - maistro-engine#ADR-073
  - maistro-engine#SPEC-062126-5d56
tests:
  - packages/maistro-core/tests/config/test_config_store.py
  - packages/maistro-server/tests/test_config_routes.py
contracts:
  - boundary
  - behavioral
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062226-fb23: ConfigStore — DB model, caching, CLI, and admin API

## Context

ADR-078 makes the database the online source of truth for hot-editable config (Sentinel
policy, RLPHD weights, feature flags, model registry/routing rules, general tunables), with
RBAC-gated edits and human-readable export — but explicitly left "the DB config table schema
and the caching/invalidation strategy" as a follow-up SPEC. ADR-062226-674b adds a maturity ladder
(Tunable → Enumerated → Locked) for implementation-defined constants, and names ConfigStore
as the mechanism Tunable-stage constants are backed by. Today there is no `ConfigStore`
implementation at all — `maistro.config.loader`/`settings.py` only cover the *static*
bootstrap-file path ADR-078 explicitly scoped as non-hot-editable (DB connection, secrets).
This SPEC builds the online half: the table, the store, the CLI, and the API surface an admin
UI calls.

## Goals

- Define the DB table schema for config entries: key, typed value, the ADR-062226-674b ladder stage
  (`tunable`/`enumerated`/`locked`), allowed-value constraints (range for `tunable`, closed set
  for `enumerated`), last-modified principal/timestamp, and audit linkage.
- Implement `ConfigStore` (ADR-078's `Protocol`: `get`/`set`/`export`) against that table, with
  an in-process cache invalidated on write (no polling) so reads stay off the DB hot path.
- Add `maistro config` CLI subcommands: `get <key>`, `set <key> <value>`, `list [--prefix]`,
  `export [path]`, `restore <path>` (explicit, never automatic per ADR-078's "export is a
  derived artifact... read back only by an explicit restore").
- Add `maistro-server` API routes: `GET /config`, `GET /config/{key}`, `PUT /config/{key}`,
  `POST /config/export`, `POST /config/restore` — all RBAC-gated per ADR-068, all writes
  audited.
- Define the response/request shapes an admin UI needs to render a config list with current
  value, stage, allowed range/set, and edit history — UI implementation itself is out of scope
  (see Non-goals), but the API must carry everything the UI needs without a second round-trip.

## Non-goals

- The admin UI's actual frontend implementation (React components, routing) — this SPEC fixes
  the API contract the UI calls; building the UI is separate follow-up work once this lands.
- Migrating any specific existing hardcoded constant (e.g. memory decay rates, RLPHD theta) to
  ConfigStore — each subsystem's own SPEC (e.g. SPEC-062126-5d56) decides if/when to adopt it.
- The drift/conformance gate on policy changes (ADR-073/ADR-074) — unchanged, out of scope per
  ADR-078 itself.
- Secret storage/rotation — secrets stay in Vault per ADR-078, never in this table.
- Multi-tenant config partitioning (Stronghold, ADR-019).

## Decision

### Table schema

```sql
CREATE TABLE config_entries (
    key             TEXT PRIMARY KEY,
    value           JSONB NOT NULL,
    value_type      TEXT NOT NULL,              -- 'int' | 'float' | 'bool' | 'str' | 'enum'
    stage           TEXT NOT NULL DEFAULT 'tunable',  -- ADR-062226-674b ladder: tunable|enumerated|locked
    allowed_range   JSONB,                       -- {"min": ..., "max": ...} for tunable numerics
    allowed_values  JSONB,                       -- [...] closed set for enumerated
    description     TEXT NOT NULL,
    updated_by       TEXT NOT NULL,               -- principal id
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

A `locked` entry is removed from this table entirely (ADR-062226-674b: locked constants go back to
being plain Python module constants, not DB rows) — so this table only ever holds `tunable`
and `enumerated` entries; `stage` distinguishes the two without needing a separate table.

### `ConfigStore` implementation

```python
class DbConfigStore:
    def __init__(self, pool: AsyncConnectionPool, cache: ConfigCache) -> None: ...

    async def get(self, key: str) -> ConfigValue:
        if cached := self._cache.get(key):
            return cached
        row = await self._fetch(key)
        self._cache.put(key, row.value)
        return row.value

    async def set(self, key: str, value: ConfigValue, *, principal: Principal) -> None:
        await self._authorize(principal, key)          # ADR-068 RBAC
        self._validate_against_stage(key, value)        # range/enum check per stage
        await self._write(key, value, principal)
        await self._audit(key, value, principal)        # ADR-037 event
        self._cache.invalidate(key)

    async def export(self) -> bytes:
        rows = await self._fetch_all()
        return yaml.safe_dump({r.key: r.value for r in rows}, sort_keys=True).encode()
```

`ConfigCache` invalidates the single changed key on every `set` (not a full-cache flush) —
writes are infrequent (admin-driven) and reads are hot-path, so per-key invalidation keeps
reads cheap without staleness beyond the write itself.

### CLI

```bash
maistro config list [--prefix sentinel.]
maistro config get sentinel.threshold.default
maistro config set sentinel.threshold.default 0.75
maistro config export config/snapshot-2026-06-22.yaml
maistro config restore config/snapshot-2026-06-22.yaml   # requires --confirm; never implicit
```

`maistro config restore` is the only command requiring an explicit `--confirm` flag and prints
a diff (current DB state vs. the file being restored) before applying — restoring is the one
operation that can silently overwrite live tunables.

### API routes (`maistro-server`)

| Route | Method | Auth | Notes |
|---|---|---|---|
| `/config` | GET | RBAC: config.read | Lists all entries with key/value/stage/range-or-set/updated_by/updated_at |
| `/config/{key}` | GET | RBAC: config.read | Single entry, same shape |
| `/config/{key}` | PUT | RBAC: config.write | Body: `{value}`; 403 if `locked` (no longer a DB row, route 404s instead) |
| `/config/export` | POST | RBAC: config.export | Returns YAML/JSON snapshot bytes |
| `/config/restore` | POST | RBAC: config.restore | Body: snapshot bytes; distinct, narrower RBAC scope than `config.write` since it's a bulk overwrite |

`config.restore` is intentionally a separate RBAC scope from `config.write` (ADR-068 tier
ladder) — being allowed to edit one tunable does not imply being allowed to bulk-overwrite the
whole table from a file.

## Acceptance criteria

- [ ] `config_entries` table exists with the schema above; `locked`-stage constants are never
      persisted as rows (ADR-062226-674b compliance: locked = plain constant, not DB-tracked).
- [ ] `DbConfigStore.get`/`set`/`export` implement ADR-078's `ConfigStore` protocol exactly.
- [ ] `set()` rejects an unauthorized principal (RBAC, ADR-068) before any write.
- [ ] `set()` rejects a value outside `allowed_range` (tunable) or not in `allowed_values`
      (enumerated).
- [ ] Every successful `set()` emits an audit event (ADR-037) and invalidates only the changed
      key's cache entry.
- [ ] `export()` produces a snapshot that `restore` can read back byte-for-byte equivalent to
      the DB state at export time.
- [ ] `maistro config restore` without `--confirm` is a no-op (prints the diff, applies nothing).
- [ ] All five API routes enforce their stated RBAC scope and return 401/403 for unauthorized
      callers.
- [ ] `PUT /config/{key}` on a `locked`-stage (no longer existent) key returns 404, not 403 —
      the key genuinely isn't config-store-backed anymore.

## Testing

- `packages/maistro-core/tests/config/test_config_store.py` (new): get/set/export round-trip,
  cache invalidation on write, RBAC rejection, range/enum validation rejection, audit event
  emission.
- `packages/maistro-server/tests/test_config_routes.py` (new): all five routes, RBAC matrix,
  restore round-trip via API, 404 on a locked/nonexistent key.

## Open questions

- Whether `ConfigCache` needs cross-process invalidation (e.g. via the events bus, ADR-086) for
  multi-replica deployments, or whether a short TTL alongside per-key invalidation is
  sufficient for v0 — left to the implementation PR; single-replica homelab deployment
  (Agent Conductor) doesn't need it, but a future multi-replica deployment would.
- Whether the admin UI (follow-up, not this SPEC) renders `enumerated` entries as a dropdown
  and `tunable` numerics as a bounded slider/input, or some other widget mapping — deferred to
  the UI SPEC.

## References

- [ADR-078: Configuration Management](../adr/ADR-078-configuration-management.md)
- [ADR-062226-674b: Constant tunability ladder](../adr/ADR-062226-674b-constant-tunability-ladder.md)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- `packages/maistro-core/src/maistro/config/` — existing static bootstrap-file loader (unchanged
  by this SPEC; that path stays file-based per ADR-078's read-order split).
