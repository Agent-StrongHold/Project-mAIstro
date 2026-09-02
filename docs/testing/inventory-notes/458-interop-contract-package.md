---
inventory-delta:
  packages/maistro-core/tests: +14
  tests/: +1
---

# #458 importable interoperability contract

Branch: `m2/870` (rebuild of PR #870's lane on current develop; the PR branch
`chatgpt/m1-458-interop-contract-package` became too divergent to repair in
place). Base: `develop@ba2b6c9c4685916080aa66d7fc172a2afd973800`.

This change owns the importable `maistro.interop` contract surface and focused
contract evidence for the published M1 interoperability ontology. The live
#458 acceptance contract was clarified after the original branch was cut, so
this lane also carries the smallest in-authority v1 schema correction needed to
add canonical Agent/Goal semantics without creating a Goal runtime or touching
product-owned adoption code.

## In bounds

- `packages/maistro-core/src/maistro/interop/**`
- focused `packages/maistro-core/tests/interop/**`
- `quality/shared-interop-ontology-v1.json` and `tests/test_shared_interop_ontology.py` only to keep the published schema and executable contract in lockstep
- `docs/architecture/INTEROP-ONTOLOGY-v1.md`
- reachability bookkeeping for the two new library modules (`quality/reachability-baseline.json`, `quality/reachability-dispositions.json`, `quality/ratchet-authorizations.json`)
- the `CORE_PUBLIC_SURFACE` list in `scripts/verify-wheel-imports.py`, which the
  enumeration ratchet requires to name every importable maistro subpackage
- this #458-specific evidence note

## Out of bounds

- product migration/adoption code
- Hive/Conductor, Canvas, Turing, Evolve, Design Studio, and Invocation implementation
- canonical execution internals (`container.py`, `runs/**`, `graph/durable_runs/**`)
- a new Goal store/reconciler; M3 #804/#805/#806 own Goal reconciliation behavior
- cross-product execution parity owned by #459
- convergence-freeze enforcement owned by #460
- migrations, workflow YAML, reachability discovery machinery, shared DI, and shared ratchet machinery
- `quality/vulture-baseline.json` (no edit is needed; see below) and every other
  shared tolerance ledger

## Contract correction

The published v1 contract advances `1.0.0` → `1.1.0`, a compatible additive
revision. It preserves every existing canonical identity while adding the live
#458 semantics the `1.0.0` snapshot omitted:

- `Agent` is canonical `agent_id`, Workspace-scoped, and remains an actor rather than a runtime;
- `Goal` is canonical `goal_id` plus exact `goal_revision`, Project-scoped;
- `Agent -> Goal` is accountability with exactly one owning Agent per Goal at a time;
- `Goal -> Goal` records optional Subgoal lineage;
- `Goal -> Graph` is execution-strategy selection, not ownership or physical containment;
- `Goal -> Run` is execution evidence and is optional for infrastructure/system Runs;
- `Persona -> Agent` is behavioral flavor and carries no authorization meaning;
- physical execution remains `Graph -> Run -> NodeRun -> Attempt -> ExecutionRuntime`;
- `GraphExecutionState` remains traversal state keyed by the Run identity, not another lifecycle;
- Run success/failure remains evidence and cannot silently become Goal terminal truth.

The executable/published mismatch for `Provider` found on earlier heads stays
corrected: Provider has no concept-level `parent` field, matching the published
schema, while `Capability -> Provider` remains an explicit required-lineage edge.

## Test movement

- `packages/maistro-core/tests` +14: `interop/test_contract.py` proves that
  the executable registry serializes exactly to
  `quality/shared-interop-ontology-v1.json`; product projections must carry
  canonical identity fields; a Goal projection must carry the exact canonical
  `goal_revision`; unknown product-local shared concepts are rejected;
  execution/effect references preserve required parent and scope identities;
  Goal requires Project scope without making Goal a mandatory Graph/Run parent;
  Agent/Goal accountability stays distinct from Goal/Graph strategy and
  Goal/Run evidence; incompatible major versions and malformed versions fail
  loudly; broken lineage/endpoint/cardinality/owner/identity definitions fail
  at construction; and the canonical registries are immutable. Both the
  registry-method form consumed by the #459 parity harness
  (`tests/cross_product_parity/`) and the exported module-level form are
  exercised.
- `tests/` +1: the frozen-schema suite gains
  `test_goal_is_project_scoped_versioned_accountability_not_execution`, and the
  lineage/consumer tests are renamed to state the physical-chain and
  later-consumer semantics they actually pin (no count change from renames).

## Quality-ledger discipline

- The validators exist as `InteropOntology` methods (the form the merged #459
  parity harness already calls) plus equivalent module-level functions
  re-exported through `maistro.interop.__all__`; the exported names are live
  reviewed public API with **zero new Vulture identities**, so no ledger edit
  or gate change is needed or made.
- `maistro.interop` is added to `CORE_PUBLIC_SURFACE` in
  `scripts/verify-wheel-imports.py`: the package is stdlib-only and importable
  from a bare install, which is exactly what the wheel-imports job should
  assert and what the enumeration ratchet requires to be listed.
- The two new modules are unreachable-by-construction library surface. They are
  banked in `quality/reachability-baseline.json`, carry a LIBRARY disposition in
  `quality/reachability-dispositions.json` (subsystem "Shared contracts and
  config"), and are covered by a reviewed grant in
  `quality/ratchet-authorizations.json`. Under the #542 trusted-base policy a
  new grant takes effect only once it has landed, so the reachability
  provenance adapter stays red on this branch's own synthetic merge until the
  grant is in the base — the documented two-merge sequence, not a gate bypass.

The implementation remains metadata/validation over canonical semantic owners.
It creates no second Workspace/Project/Agent/Goal/Graph/Run domain model, no
Goal reconciler, no scheduler, and no product-specific execution path, and it
does not claim the #459 cross-product runtime parity proof.
