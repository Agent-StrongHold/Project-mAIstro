---
inventory-delta:
  packages/maistro-core/tests/: +14
---

# #458 importable interoperability contract

Branch: `chatgpt/m1-458-interop-contract-package`
Original base: `develop@fdb6bcbb83b6e362f8fbf922bb41f737355a71bd`

This branch owns the importable `maistro.interop` contract surface and focused contract evidence for the published M1 interoperability ontology. The live #458 acceptance contract was clarified after the branch was cut, so this lane also carries the smallest in-authority v1 schema correction needed to add canonical Agent/Goal semantics without creating a Goal runtime or touching product-owned adoption code.

## In bounds

- `packages/maistro-core/src/maistro/interop/**`
- focused `packages/maistro-core/tests/interop/**`
- `quality/shared-interop-ontology-v1.json` and `tests/test_shared_interop_ontology.py` only when required to keep the published schema and executable contract in lockstep
- `docs/architecture/INTEROP-ONTOLOGY-v1.md`
- this #458-specific evidence note

## Out of bounds

- product migration/adoption code
- Hive/Conductor, Canvas, Turing, Evolve, Design Studio, and Invocation implementation
- canonical execution internals (`container.py`, `runs/**`, `graph/durable_runs/**`)
- a new Goal store/reconciler; M3 #804/#805/#806 own Goal reconciliation behavior
- cross-product execution parity owned by #459
- convergence-freeze enforcement owned by #460
- migrations, workflow YAML, reachability ledgers, shared DI, and shared ratchet machinery
- `quality/vulture-baseline.json` while PR #798 owns that ledger

## Contract correction

The published v1 contract is now `1.1.0`, a compatible additive revision. It preserves every existing canonical identity while adding the live #458 semantics that the previous `1.0.0` snapshot omitted:

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

The earlier executable/published mismatch for `Provider` is also corrected: Provider has no concept-level `parent` field, matching the published schema, while `Capability -> Provider` remains an explicit required-lineage edge.

## Evidence

Fourteen focused behavioral contract tests now prove that:

- the executable registry serializes exactly to `quality/shared-interop-ontology-v1.json`;
- product projections must carry canonical identity fields rather than independently named IDs;
- a Goal projection must carry the exact canonical `goal_revision` context;
- unknown product-local shared concepts are rejected;
- execution references preserve required parent and scope identities;
- Goal requires Project scope without making Goal a mandatory Graph/Run parent;
- governed-effect references preserve `Capability -> Provider -> Binding -> Invocation` lineage;
- Agent/Goal accountability remains distinct from Goal/Graph strategy and Goal/Run evidence;
- incompatible ontology major versions and malformed versions fail loudly;
- required physical lineage cannot silently disappear;
- parent/scope relations cannot point at unknown concepts;
- typed relationships cannot target unknown concepts or use unreviewed cardinalities;
- canonical concept/relationship registries are immutable; and
- owner and identity metadata cannot silently move outside canonical `maistro.*` / `*_id` semantics.

The repository-level `tests/test_shared_interop_ontology.py` also pins v1.1 Agent/Goal owners and identities, exact Goal revision semantics, Project→Goal scope, physical execution lineage, effect lineage, and the M3 Workspace-Agent/Design-Studio consumer declarations.

## Quality-ledger discipline

The existing public validation methods are intentional importable API and were reported by Vulture as reviewed-public-surface candidates. The repository's gate explicitly requires those identities to be banked through `scripts/check-vulture-baseline.py --update`, not by deleting the API or hand-editing the ledger.

PR #798 currently owns `quality/vulture-baseline.json`, so this branch deliberately does not modify that shared ledger. Current-head CI is allowed to report the collision honestly; once #798 clears, #870 must re-evaluate the exact current synthetic merge and bank only still-live reviewed identities through the approved mechanism.

The implementation remains metadata/validation over canonical semantic owners. It creates no second Workspace/Project/Agent/Goal/Graph/Run domain model, no Goal reconciler, and no product-specific execution path, and it does not claim the #459 cross-product runtime parity proof.
