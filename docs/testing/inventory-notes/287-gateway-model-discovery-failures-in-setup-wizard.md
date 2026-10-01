---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
---

# 287 — Gateway model-discovery failures in the setup wizard

Delta: the new `test_gateway_model_discovery.py` adds 18 pytest node IDs to
the `packages/hive-conductor/backend/tests` suite (the wizard's Playwright
specs in `packages/hive-conductor/frontend/e2e/` are not a pytest suite and
are not part of this ledger).

## Problem

At `develop`, the Setup wizard fetched the gateway model catalog, swallowed
every failure, and presented a curated hard-coded list with no indication it
differed from live gateway state. A broken or unauthorized gateway therefore
looked usable, and a failed fetch was indistinguishable from a valid catalog.

## What changed

### Frontend — `packages/hive-conductor/frontend/src/pages/Setup.tsx`

- Discovery lifecycle state `modelCheck: pending | ok | failed` replaces the
  silent catch; the curated `FALLBACK_MODELS` stay as an offline baseline but
  are always labelled as such.
- Every failure class renders its own actionable message and
  `data-testid` (`model-error-auth|not_found|server|network|empty|malformed|
  http|unexpected`) plus a **Retry gateway discovery** button (effect keyed on
  `fetchKey`).
- Provenance status line (`data-testid=model-discovery-status`): "N models
  discovered from the gateway" vs "Curated suggestions — … UNVERIFIED" vs the
  manual-entry line.
- Manual entry is reachable (`model-manual-toggle`); curated and manual
  selections require the explicit unverified-availability acknowledgement
  (`unverified-ack` checkbox) before **next** enables; the acknowledgement is
  reset when the mode changes.
- Confirm step shows `router: <model> · unverified`
  (`router-model-unverified`) when the catalog is not verified.
- `finish()` runs a final preflight: it re-queries `/v1/settings/models` and
  only marks the effective default model `verified` when the gateway answers
  AND lists it; otherwise the completion payload carries
  `model_availability: "unverified"`.

### Backend — `packages/hive-conductor/backend/routes/settings.py`

- `GET /v1/settings/models` is now additive: `models` is unchanged for
  existing consumers, plus `discovered`, `source`
  (`gateway`/`stored_default`), and a sanitized `error {kind, message}`
  (`None` on success). `_discover_gateway_models()` never raises; failures
  are classified (`_classify_http_status`, TLS via exception-chain walk,
  `UnsupportedProtocol` → `policy`, JSON/shape failures → `malformed`,
  empty catalogs stay `source: gateway` with kind `empty`) and logged at
  warning level with class-only detail (no URLs, keys, or bodies).
- `_fetch_available_models()` keeps its exact list-returning contract.

### Backend — `packages/hive-conductor/backend/routes/setup.py`

- `SetupCompleteBody` gains optional `model_availability:
  "verified"|"unverified"|None` (additive; `extra="ignore"` semantics for
  pre-existing callers are unchanged). When provided, the verdict is
  persisted into the setup `config` record next to `default_model`, so a
  degraded install is explicitly recorded rather than indistinguishable from
  a verified one.

### Removed

- `packages/hie-conductor/` — a typo'd package directory introduced by the
  first draft of this change, containing a corrupted duplicate of Setup.tsx
  (broken JSX, duplicated account cards, an out-of-scope module entry).
  Nothing referenced it; its intent is implemented properly in the real
  `packages/hive-conductor/frontend/src/pages/Setup.tsx`.

## Reconciliation notes

- The wizard runs pre-login and `/v1/settings/*` is auth-gated by design, so
  the dominant in-wizard failure is the 401 auth class; deeper gateway-side
  TLS/SSRF/policy enforcement remains with the downstream install/release
  owner (#86). The `/v1/settings/models` contract now distinguishes those
  classes when they occur, which is what this issue required.
- The wizard treats a *pending* fetch as non-blocking (offline usability);
  the final preflight at completion time is what prevents a never-answered
  catalog from being recorded as verified.
