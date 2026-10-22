---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-design/tests: +25
---
# auto-793-55af

#793 (M7-A4, domain packs of one Run) adds, on purpose:

- `packages/maistro-design/tests/test_packs.py` (+25 collected after the
  parametrized expansion): the `maistro_design.packs` contract — one
  registry over three in-repo YAML manifests (`product`/`game`/`book`),
  Goal-scoped Rubric catalog instantiation with identity minted per call,
  canonical `GraphTemplate` projection, and every pack executed through the
  real durable executor (`run_durable_graph` + `InMemoryDurableRunStore`,
  stub phase nodes per the `tests/graph/durable_runs` pattern), including
  the same-Goal-through-two-packs shared-identity test.
- `packages/hive-conductor/backend/tests/test_design_packs_route.py` (+4):
  `GET /design/packs` lists exactly the three packs with one uniform entry
  shape, no per-pack route exists in the OpenAPI schema, and canvas appears
  only under `execute_backends` (a binding), never as `pack_id`.

No tests were removed or renamed. The criterion-by-criterion mapping and the
deliberate scope boundaries (fence points are declared data, not executed
gates; phase kinds are loop-runtime bindings stubbed in CI) are recorded in
[793-domain-packs.md](793-domain-packs.md).
