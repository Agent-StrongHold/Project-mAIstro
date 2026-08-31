---
id: ADR-045
title: Canvas Studio ↔ maistro-server /v2/canvas Cutover
repo: maistro-engine
kind: adr
status: Denied
created: 2026-05-09
denied: 2026-08-31
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
  - maistro-engine#ADR-042
  - maistro-engine#ADR-043
  - maistro-engine#ADR-044
  - maistro-engine#ADR-019
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-09
  - status: Denied
    date: 2026-08-31
---

# ADR-045: Canvas Studio ↔ Engine Cutover

## Current disposition

This proposal is **Denied** as a product-boundary decision. It assumed a separate
Canvas Studio application whose identity would be preserved while its API was
migrated. The current product contract in #286 and #95 instead makes **Design
Studio** the parent creative-production surface and **Canvas** one
visual/fixed-page/rendering capability it consumes.

The API-migration observations below remain historical engineering context and
may inform #95 where they still match the live tree. They do not authorize a
separate Studio identity, a parallel product state model, or a compatibility
path that bypasses the canonical Design Studio product boundary.

## Context

`canvas-studio-poc` PR #5 retired `server.js` and replaced it with a
local FastAPI app (`server/main.py`) that preserves the legacy
`/api/books`, `/api/templates`, `/api/characters`, `/api/print/*`,
`/api/export`, `/api/generation-attempts`, `/api/layout-versions` shape
against the same Postgres on `:5440`. That was a **Node-tier removal**,
not a model unification — the data is still legacy JSONB blobs.

Meanwhile `maistro-server` mounts the typed `/v2/canvas/*` routes from
ADR-042 against the new `asset_*` tables. The two halves don't yet
talk to each other.

## Decision

Cut canvas-studio-poc's FastAPI over to the engine's typed routes in
**three phases**, sequenced after ADR-044's Phase 3 (so legacy data is
migrated before frontend call sites move).

### Phase A — Read-side mirror (~1 week)

`server/main.py` adds a thin proxy layer: when `MAISTRO_ENGINE_URL` is
set, every read endpoint (GET books / templates / characters / etc.)
calls the corresponding `/v2/canvas/*` route on the engine in addition
to its local DB query, compares both, and logs divergences. Writes
remain local-only.

The proxy is **opt-in via env var**; default behaviour is unchanged.
Output is structured logs the operator can grep.

Done when:

- Production canvas-studio-poc runs in mirror mode for one week with
  zero unexplained divergences.
- The `frontend/server/lulu` and `frontend/server/mcp` callers
  unchanged — they're orthogonal Python services using their own
  FastAPI surfaces.

### Phase B — Read-side cutover (~1 week)

Reads switch to engine-first; the local DB becomes a fallback only.
Frontend code is unchanged (the FastAPI proxy translates between the
legacy JSONB shape and the new typed shape, using the bridge from
ADR-044 §"Bridge").

Done when:

- All `GET /api/...` calls on canvas-studio-poc resolve via
  `/v2/canvas/*` first, with the local DB only used when the engine
  is unreachable.
- p99 latency overhead from the extra hop is below 50ms in the
  default-deployment topology (engine and POC on the same machine).

### Phase C — Write cutover (~2 weeks)

Writes follow reads. Each `POST /api/...` is rewritten to translate
into one or more `/v2/canvas/*` calls. The local Postgres tables on
`:5440` become read-only and eventually drop out of the deployment.

Done when:

- `pg` references in `canvas-studio-poc/server/main.py` are removed.
- The `:5440` Postgres instance can be shut down without the frontend
  noticing (verified by integration test).
- canvas-studio-poc's `package.json` no longer pins a Postgres image
  in its docker-compose.

### Auth and CORS

The engine's `/v2/canvas/*` routes inherit `maistro-canvas/auth.py`'s
API-key scheme. canvas-studio-poc's FastAPI proxy holds an
engine-issued service key in an env var (`MAISTRO_ENGINE_KEY`). CORS
on the engine side allows the canvas-studio origin only; the
existing `*` policy on canvas-studio-poc's FastAPI stays in place
behind the proxy.

### Rollback

Each phase ships behind a feature flag:

- Phase A: `MAISTRO_MIRROR=on/off`
- Phase B: `MAISTRO_READS=engine|local`
- Phase C: `MAISTRO_WRITES=engine|local|both`

Reverting any phase is a flag flip and a redeploy. No data migration
is required to revert; the legacy schema stays present until the
end of Phase C.

## Cross-service contracts

The engine's `/v2/canvas/*` endpoints are the consumer-driven
contract per ADR-032 §3. canvas-studio-poc publishes its expected
schema as `canvas-studio-poc/contracts/maistro-engine.json`; the
engine's CI runs the contract suite on every PR touching
`asset_routes.py` or `asset_store.py`.

Specific contracts:

- `POST /v2/canvas/asset-instances` accepts the wire shape defined
  in `AssetInstanceIn` (ADR-042). Adding required fields is a major
  bump.
- `POST /v2/canvas/canvases/{id}/plan` returns the wire shape
  defined in `RenderPlanModel`. Removing fields is a major bump.
- Status code mapping (ADR-042 §"Status code mapping") is part of
  the contract; changing a 422 to a 400 (or vice versa) is a major
  bump.

## Boundary contracts

- The proxy in Phase A is **read-only**; it must not double-write
  during the mirror window.
- The bridge in Phase B is **lossless on the legacy fields**: every
  field present on a legacy `Book` JSONB row survives the round-trip
  through `/v2/canvas/books` and back.
- Phase C's write rewrite is **transactional per top-level POST**:
  either every engine call succeeds, or the proxy rolls back (best-
  effort) and reports the failure. There is no partial state where
  half the writes landed on the engine and half remained local.

## Behavioural contracts

- During Phase A, the canvas-studio frontend's user-visible behaviour
  is **byte-identical** to pre-Phase-A.
- During Phase B, divergence between the engine and the local DB is
  **logged but not enforced**; the frontend continues to work even
  if the engine returns an unexpected shape.
- After Phase C closes, the `:5440` Postgres can be removed without
  a frontend restart.

## Consequences

- The `:5440` Postgres becomes a transitional artefact. Operations
  teams need a runbook for graceful shutdown.
- Engine-side latency budgets matter: the canvas-studio frontend
  expects writes under 200ms p99 on auto-save; the engine must hold
  that. Performance review is part of Phase B exit criteria.
- The engine becomes the source of truth for canvas data; backups
  shift to the engine's Postgres. canvas-studio's `:5440` Postgres
  becomes a stale read-replica for the deprecation window.

## Out of scope

- Multi-tenant per-org cutover sequencing for `stronghold` — separate
  ADR. canvas-studio-poc is single-tenant.
- Replacing the Lulu print proxy (`/api/print/*`) — that's already
  a thin pass-through to the Python Lulu service, not engine-bound.
- Switching the BookWizard frontend to the engine's `LayerKind`
  taxonomy in the UI — separate ADR after the data is migrated.

## Source references

- `canvas-studio-poc/server/main.py` — current local FastAPI.
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_routes.py`
  — engine's `/v2/canvas/*` surface.
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
  — bridge target.

## Links

- PR: (this PR)
- Follow-up: ADR-046 (legacy schema removal in canvas-studio-poc),
  ADR-047 (frontend Mantine + LayerKind UI swap).
