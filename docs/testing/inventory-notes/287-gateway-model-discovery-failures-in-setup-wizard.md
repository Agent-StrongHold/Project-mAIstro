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
- Only a catalog the backend explicitly marks `discovered: true` renders as
  discovered. A 200 that carries `discovered: false` — the backend's
  stored-default substitute plus its sanitized failure class
  (`not_configured`, `tls`, `policy`, …) — takes the failure path with the
  backend's own kind, so gateway-side TLS/policy failures are distinguishable
  in the wizard, and the substitute is surfaced separately as the cached
  default (`data-testid=model-cached-default`), distinct from the curated
  suggestions.
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
  only marks the effective default model `verified` when the backend reports
  `discovered: true` AND lists it; otherwise the completion payload carries
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

## CI repair (merge-queue round, head 5a4103e10)

The new step-0 gate — next stays disabled while discovery has failed and the
unverified acknowledgement is unchecked — correctly classified the e2e
harness itself: `tests/e2e/session.ts` `setupIfNeeded()` filled the conductor
name and clicked Next, but the harness ships no gateway, so
`/v1/settings/models` returns `discovered:false` (`not_configured`), the
acknowledgement rendered, and every spec that boots through setup timed out
waiting on a disabled button (~40 failures in `hive-conductor-e2e-ui`, which
took the `integration-scope` aggregator down with it).

Repair: `setupIfNeeded()` now waits briefly for the
`unverified-ack` checkbox and checks it when it renders (the bounded wait
gives up if a real catalog is ever discovered, leaving the already-unlocked
step untouched). The harness therefore walks the same explicit
acknowledged-unverified path a human must. No spec count changed: the
compose Playwright suite is not part of this pytest ledger, and the pytest
delta above is still +18 node IDs (`test_gateway_model_discovery.py` also
lost an accidental `return out` that tripped `PytestReturnNotNoneWarning`;
assertions unchanged).

Local proof: `docker compose -f docker-compose.test.yml --profile test up
--build --abort-on-container-exit --exit-code-from e2e-tests e2e-tests` →
**106 passed (2.9m), exit 0** (host port 8101 was occupied by an unrelated
container, so the run used a local-only compose override dropping the host
port mapping; the tests address the service over the compose network at
`http://hive:8101`, so the exercise is identical).

## 2025-10-01 round 3 — develop sync (f8cc3597) resolved on top

The preserved in-progress merge of develop (`e2b2dfa0`, then its descendant
`f8cc3597` — the lane's develop base) was resolved in place. Both sides of
each conflict are retained:

- `backend/routes/setup.py` — `SetupCompleteBody` keeps develop's declared
  defaults (`DEFAULT_CONDUCTOR_NAME` / `DEFAULT_DEFAULT_MODEL` from
  `maistro.config.first_run`, per the #443 "never restate a default" rule)
  and #287's `model_availability` verdict field, whose explicit
  `"unverified"` is still preserved server-side, never upgraded.
- `Setup.tsx` — develop's declaration seeding (empty `routerModel` =
  server default, seeded `adminUsername`, `touchedModules`, resolved
  hardware) coexists with #287's discovery lifecycle: per-class error
  alerts, retry, cached-default line, manual entry, the unverified
  acknowledgement gate, and the finish()-preflight `model_availability`.
  On a *discovered* catalog the wizard still re-points the selection to a
  catalog member (also from an empty seed) so the preflight can actually
  verify the effective model; the operator retains develop's explicit
  "Server default (recommended)" opt-out. The confirm step shows
  `router: <model|server default>` plus the `router-model-unverified` mark.
- `backend/tests/test_setup_first_run_questions.py` — the #443 parity hinge
  now documents the one accepted field that is NOT an operator question:
  `model_availability` (#287 preflight verdict). The check is strengthened,
  not loosened: the declaration plus the documented non-question set must
  exactly equal `SetupCompleteBody.model_fields`, so a future control field
  cannot silently dodge parity.

Harness repair (frontend specs only, no product change; mirrors the
committed `session.ts` pattern from round 2): `frontend/e2e/setup.spec.ts`
flows acknowledge the unverified gate when it renders (they predate #287
and only ever ran where a gateway answered), and the retry spec no longer
counts on React StrictMode's dev-only double mount fetch — it registers
the recovered-catalog route after the failure renders, which is
environment-agnostic (Playwright matches routes most-recent-first).

Local proof this round: backend `test_gateway_model_discovery.py +
test_setup_first_run_questions.py + test_setup_guard.py` → 44 passed; full
`packages/hive-conductor/backend/tests` → **3098 passed, 5 skipped**;
`check-suite-inventory.py` → ok (3103); vulture ratchet balanced
(1378 = 1378, unclassified 0); frontend `tsc` + `vite build` + eslint
(0 errors, 95/96 warnings); `frontend/e2e` setup specs against the live
compose hive → **15 passed**; named gate `hive-conductor-e2e-ui`
(compose `e2e-tests`) → **113 passed (4.0m), exit 0** — the count moved
106 → 113 because develop added `dashboard-metrics-states.spec.ts` (its
own inventory note), not a ledger change for this suite; the
`hive-conductor-e2e` leg (compose `api-tests`) → 10 passed, 13 skipped,
exit 0; `ci_merge_group_scope.py` → `hive_e2e=true`;
`check-integration-scope.py` (merge_group, this scope, all in-scope legs
success) → "ok: integration scope satisfied".
