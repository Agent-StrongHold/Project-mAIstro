---
inventory-delta:
  packages/maistro-core/tests: +30
---
# claude-ws-1047-usermodelfact-type-usermodelstore-protoc-1821

+30 core tests, all new and none moved or removed: `tests/memory/user_model/`
covers the new `UserModelFact` record and `InMemoryUserModelStore` (revision
lineage, owner isolation, tombstones that block every wording a lineage held,
one lineage per statement, invariants and enum rehydration; 11 tests) and same-user promotion, cross-user
refusal, reinforcement, replay no-op, contradiction review, correction,
audited refusals and tombstone non-recreation (19 node IDs including
parametrized cases) for #1047.
