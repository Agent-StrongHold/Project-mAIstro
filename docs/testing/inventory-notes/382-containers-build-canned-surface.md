---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# 382-containers-build-canned-surface

Issue #382 ("Implement the Containers build path or remove its canned-success
surface") is resolved on `develop` by the **removal** branch of its own
disjunction. The canned handler (`{"status": "building", "log": "Building..."}`)
was eliminated by the #389 audit (#1716): `POST /v1/containers/build` and
`POST /v1/containers/suggest` now refuse with an explicit `501`
("not implemented in this deployment; no build was started"), the OpenAPI
schema marks both operations unsupported, `quality/api-route-contracts.json`
records the `unsupported-501` disposition, and
`scripts/check-api-route-contracts.py` fails CI on any regression to a
pure-constant canned handler. The SPA has no build affordance at all
(`pages/Containers.tsx` carries zero build/suggest references), and
`scripts/check-frontend-api-routes.py` proves every frontend call resolves to a
registered route — so no UI state can be derived from a build that never ran.

## What the +2 add

Parametrized route test
`test_unsupported_containers_routes_refuse_even_with_a_reachable_backend`
(both `/build` and `/suggest`) in `test_containers_routes.py`. The pre-existing
`501` tests ran with no Docker socket, so they could not distinguish "refuses
because unimplemented" from "refuses because unreachable". The new test makes
the backend fully reachable (`_socket_present`), records every Docker Engine
API call the route attempts, and requires:

- the response is `501` with a non-empty `detail`, and the body carries
  **only** `detail` — no success-shaped `status`/artifact/digest payload can
  accompany a refusal;
- **zero** Engine API calls are attempted — no build input reaches the daemon
  in any backend state, so no ungoverned execution path exists to produce an
  artifact, digest, or Run.

If a build path is ever reintroduced without its governed executor, the test
fails on the request the route can no longer avoid making.

## Mutation check

The canned handler was temporarily reinstated verbatim
(`return {"status": "building", "log": "Building..."}`): the new `/build` case
FAILED (`200 != 501`) while the untouched `/suggest` case still passed, then
the route was restored and all 68 tests in the two touched files passed again.

## Why not the implementation branch

Implementing builds would require the governed execution capability the issue
names (durable artifact identity/digest, terminal canonical Run, isolation,
network/credential/supply-chain controls) — a capability that does not exist on
this tree for image builds, and whose absence is exactly what the removal
branch documents. The refusal is the honest contract; this change only hardens
its evidence.

## Validation (this tree)

`uv run pytest packages/hive-conductor/backend/tests/test_containers_routes.py
packages/hive-conductor/backend/tests/test_noop_route_contracts.py -q`:
68 passed. `uv run python scripts/check-api-route-contracts.py`: OK
(279 handlers scanned, 15 audited routes registered, 0 canned).
`uv run python scripts/check-frontend-api-routes.py`: ok (178 call sites /
65 files resolve to 229 registered routes). `uv run ruff check` and
`ruff format --check` clean on the changed tree.
`uv run python scripts/check-suite-inventory.py`: 15 suites match.
