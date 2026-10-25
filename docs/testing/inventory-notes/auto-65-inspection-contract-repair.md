---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# #65 inspection contract repair

Adds two OpenAPI contract cases (list/detail), one real HTTP response serialization
case over canonical Goal/Run readers, and one canonical-only Run backlink case.
The schema checks require named, nested Goal and Run response entities; the HTTP
case verifies nullable lineage and nested retry/replan/HITL evidence survive
serialization. The canonical-only case checks immutable Goal binding precedence
and refusal for a non-member without seeding a product Run projection.

These are projection/transport tests, not proof of production Goal admission,
restart durability, canonical Goal discovery, or effect/approval navigation.

Architecture reconciliation: ADR-081226-9944 and ADR-082826-d9f5 retain canonical
identity/lifecycle authority. The response types describe an inspection DTO,
not another Goal or Run model. Missing scoped discovery APIs are not replaced
by raw-store scans. Infrastructure Runs may remain unbound to a Goal per
INTEROP-ONTOLOGY-v1; no Goal binding is fabricated for those Runs.

## Executed validation

- Before the fix, both OpenAPI cases failed because the response was an
  unstructured object. The canonical-only backlink case failed with
  `KeyError: 'goal_context'` (after fixing a missing Graph name in its fixture).
- `uv run pytest packages/hive-conductor/backend/tests -x -q`:
  **3751 passed, 19 skipped**. The focused Goal suite has **27 passing cases**;
  adjacent Run inspection/control/durability suites plus Goal inspection have
  **111 passing cases**.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py -x -q`:
  **6 passed**.
- Ruff check/format, route-permissions, frontend-typed-client,
  frontend-api-routes, api-route-contracts, and backend suite-inventory gates:
  **passed**. Exact CI vulture command: **1322 findings / 1322 reviewed
  identities**, no unbanked debt; no ledger amendment justified.
- OpenAPI dump, TypeScript generation (repeat output identical), frontend
  build, and focused ESLint: **passed**.
- A foreground Playwright check loaded the production bundle with intercepted
  HTTP responses: retry/replan/HITL provenance, exact parent Run/NodeRun ids,
  HTML escaping, parent navigation/back, and reload all passed. This is UI
  fixture evidence, not live producer or server-restart evidence.

## Remaining acceptance gaps

Goal discovery still starts with the bounded Run projection; neither scoped
Goal nor scoped Run readers currently offers discovery. Conductor's inspected
Run admission paths do not bind a canonical Goal revision. The Goal page shows
execution disposition, not the full reconciliation decision. Invocation/effect/
approval navigation and live Goal admission/restart proof remain unresolved.
The older Run-detail response also retains unstructured frontend entity types;
this repair generates the Goal-list/detail contract, not the entire Run API.
This is a partial repair, not #65 acceptance or integration approval.
