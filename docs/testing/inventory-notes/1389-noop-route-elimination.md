---
inventory-delta:
  packages/hive-conductor/backend/tests: +19
---
# #389 Inventory and eliminate success-shaped no-op API routes

The audit found shipped routes that answered `200` for operations that did
nothing: settings reload/audit/quotas, schedule history, memory
contradict/namespaces, quota outcomes, and the provider request-count column.
Every named route now either performs its implied operation against a canonical
durable owner, or refuses with an explicit `501`. The contract table is
`docs/api/route-contract-inventory.md`; the machine-checked inventory is
`quality/api-route-contracts.json`, enforced by the new
`scripts/check-api-route-contracts.py` CI gate (wired into ci.yml next to the
frontend-route gate).

## Test delta (+19, all in `packages/hive-conductor/backend/tests`)

New file `test_noop_route_contracts.py` (+15): the settings reload must
re-read its store (out-of-band write visible, unavailable store `503`); the
settings audit query returns seeded non-empty data scoped to settings actions
and `[]` only when genuinely empty; `/v1/settings/quotas` serves the same
provider panel as `/v1/quotas/providers` (and `503` when unavailable); the
schedule-history query returns seeded fire receipts scoped to authorized
Workspaces and `[]` when empty; the four unsupported routes refuse `501`
(mcp scan keeps its `404` for unknown servers); the OpenAPI schema marks the
preview (`/v1/settings/volatile`) and unsupported operations; and the
placeholder gate passes on this tree.

Updated files: `test_memory_routes.py` (+1 — the namespaces route is derived
from owned entries, empty-valid, and the contradict route now changes durable
state, asserted through the store and a re-read); `test_quotas.py` (+3 —
request_count aggregated from `usage.api_requests`, unavailable
unconfigured-gateway `503`s for providers, outcomes read from the canonical
outcome store with a seeded non-empty proof and a `503` store-failure case);
`test_containers_routes.py`, `test_mcp_routes.py`, `test_platform.py` (net 0 —
the tests that pinned the old canned responses now pin the explicit `501` /
`503` contracts).

## Implementation notes

- `services/settings_store.reload()` drops the cache before re-reading, so a
  failed read cannot answer from stale state.
- `MemoryEntry` gains a `contradictions: int = 0` field (backward-compatible
  default for persisted rows); the hard-coded `stores.memory_namespaces` seed
  is deleted, not wrapped.
- `routes/quotas.py` was rewritten around `QuotaSourceUnavailable` → `503`;
  the zeroed `_fallback_*` helpers are gone. The outcomes panel is async and
  reads the canonical store `services.feedback_service` binds.
- `routes/settings.py` reuses the provider aggregation via a lazy import (no
  module-import cycle) and maps its unavailability to `503`.
- Schedule history intentionally derives from the durable audit log rather
  than reaching into the canonical run store: the scheduler already writes
  per-fire receipts (including refused fires and canonical run ids) there,
  and Hive-keyed reads stay within the Workspace authorization the other
  schedule surfaces use. Canonical `Goal -> Graph -> Run` execution is
  untouched; this is a read surface over receipts, not a second execution
  record.
- Frontend: `KnowledgeBase.tsx` rendered `ns.count`, which no backend payload
  ever carried; it now renders the real `entry_count`.

## Validation (this tree)

`uv run pytest packages/hive-conductor/backend/tests -q`: 3016 passed / 6
skipped. `uv run ruff check` and `ruff format --check` clean on the changed
tree. `python3 scripts/check-api-route-contracts.py`: 276 handlers scanned, 15
audited routes registered, 0 canned. `check-frontend-api-routes`,
`check-public-routes`, `check-durable-table-inventory` pass. The four
unsupported-route conversions and the `503` conversions have no frontend
callers (`check-frontend-api-routes` proves the SPA only calls registered,
still-present paths).
