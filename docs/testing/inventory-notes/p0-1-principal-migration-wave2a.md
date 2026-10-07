# p0-1-principal-migration-wave2a

Workspace cutover Wave 2 Lane A — burn P0.1 `state_user_access` debt on
`develop`.

## Inventory effect

PR #1816 (`ef4871e3`) changed one existing test body in
`packages/maistro-turing/backend/tests/test_chat.py` without adding, removing,
renaming, or parametrizing tests. It records no suite-count delta. The paths
below describe migrated source files and principal-identity debt, so they are
prose rather than numeric `inventory-delta` entries.

- `packages/hive-conductor/backend/middleware/auth.py`: migrated
- `packages/hive-conductor/backend/routes/`: migrated (22 route modules)
- `packages/hive-conductor/backend/services/`: migrated (3 modules)
- `packages/maistro-core/src/maistro/identity/principal.py`: extended
- `packages/maistro-turing/backend/`: migrated (middleware + security + chat)
- `quality/principal-identity-baseline.json`: 32 -> 4

## What changed

No collected test count moved: this wave migrated production modules and
reduced the principal-identity tolerance ledger (32 → 4); the per-suite test
counts are unchanged, so no `inventory-delta:` block is recorded (the file
paths below are the migration surface, not suite deltas).

- Extended `maistro.identity.Principal` with `username`, `permissions`,
  `elevated_permissions`, and helpers (`actor_id`, `audit_label`,
  `has_permission`, `is_admin`).
- Hive Conductor `AuthMiddleware` now stamps `request.state.principal` instead
  of `request.state.user`.
- Added `services/request_principal.py` as the shared read boundary for routes
  and services.
- Migrated 22 hive-conductor route modules plus `owned_records`,
  `program_hyperagent`, and `tool_primitives`.
- Migrated maistro-turing middleware, inbound security, and chat route.

## Ratchet

`quality/principal-identity-baseline.json` reduced from **32 → 4** tolerated
entries. Remaining debt is `parallel_principal_class` only:

- `HiveUser` (hive schemas)
- `CurrentUser` (maistro-canvas auth)
- `_SubsystemIdentity` (maistro-core privilege)
- `AuthenticatedPrincipal` (maistro-server API)

## Verification

```bash
RATCHET_BASE_REV=origin/develop uv run python scripts/check-principal-identity.py
uv run pytest packages/maistro-core/tests/fitness/test_principal_identity.py \
  packages/hive-conductor/backend/tests/test_auth_middleware.py \
  packages/maistro-turing/backend/tests/test_chat.py -q
```
