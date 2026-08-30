---
inventory-delta:
  packages/maistro-core/tests/: +10
---

# #458 importable interoperability contract

Branch: `chatgpt/m1-458-interop-contract-package`
Base: `develop@fdb6bcbb83b6e362f8fbf922bb41f737355a71bd`

This branch owns only the missing importable `maistro.interop` contract surface and focused contract evidence for the already-published M1 interoperability ontology.

## In bounds

- `packages/maistro-core/src/maistro/interop/**`
- focused `packages/maistro-core/tests/interop/**`
- `quality/shared-interop-ontology-v1.json` and `tests/test_shared_interop_ontology.py` only when required to keep the published schema and executable contract in lockstep
- this #458-specific evidence note

## Out of bounds

- product migration/adoption code, including active Builders #744/#734
- Hive/Conductor, Canvas, Turing, Evolve, Design, and Invocation implementation
- canonical execution internals (`container.py`, `runs/**`, `graph/durable_runs/**`)
- cross-product execution parity owned by #459
- convergence-freeze enforcement owned by #460/#756
- migrations, workflow YAML, reachability ledgers, shared DI

## Evidence

Ten focused behavioral contract tests prove that:

- the executable registry serializes exactly to `quality/shared-interop-ontology-v1.json`;
- product projections must carry the canonical identity field rather than an independently named ID;
- unknown product-local shared concepts are rejected;
- execution references preserve required parent and scope identities;
- governed-effect references preserve Capability → Provider → Binding → Invocation lineage;
- incompatible ontology major versions and malformed versions fail loudly;
- required lineage cannot silently disappear;
- parent/scope relations cannot point at unknown concepts;
- the canonical registry is immutable; and
- owner and identity metadata cannot silently move outside canonical `maistro.*` / `*_id` semantics.

`GraphExecutionState` remains attached traversal state keyed by the Run's `run_id`: its metadata may name Run as its parent without creating a second required lifecycle edge because both concepts intentionally share the same canonical identity.

The implementation remains metadata/validation over existing canonical semantic owners. It does not create a second Workspace/Project/Graph/Run/etc. domain model, and it does not claim the #459 cross-product execution proof.
