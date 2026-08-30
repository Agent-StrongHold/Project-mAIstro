# #458 importable interoperability contract claim

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

The implementation must remain metadata/validation over existing canonical semantic owners. It must not create a second Workspace/Project/Graph/Run/etc. domain model.
