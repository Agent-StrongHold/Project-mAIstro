# feat-cutover-p0.3-client-burn-wave1

Workspace cutover Phase 0, step P0.3 — wave 1 typed-client debt burn on
`develop`.

## Inventory effect

No suite test count delta: this wave migrates hive-conductor frontend API
usage and reduces the typed-client tolerance ledger. Prose paths below
describe the migration surface, not numeric `inventory-delta` entries.

## What changed

- Added `packages/hive-conductor/frontend/src/api/entities.ts` — OpenAPI
  entity aliases from `types.gen.ts` plus a few path-derived response types
  where schemas are still loose objects.
- Migrated 13 call sites from bare `fetch(` to `lib/api` helpers (`apiGet`,
  `apiPost`, `apiPut`).
- Removed 11 hand-typed local entity declarations from pages/components in
  favor of `entities.ts` imports (Skills, Schedules, Memory, AuditLog, MCP,
  Settings, LlmProviders, TemplatePicker).
- Profile keeps one waived raw `fetch` for `/v1/chat/stream` SSE (shared client
  30s body timeout; #1423).

## Ratchet

`quality/frontend-typed-client-baseline.json` reduced:

| Metric | develop | wave 1 |
|--------|---------|--------|
| raw_fetch | 60 | 43 |
| hand_typed | 142 | 131 |

## Verification

```bash
uv run python scripts/check-frontend-typed-client.py
cd packages/hive-conductor/frontend && npm run build
```
