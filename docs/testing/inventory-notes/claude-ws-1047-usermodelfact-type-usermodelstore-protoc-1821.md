---
inventory-delta:
  packages/maistro-core/tests: +21
---
# claude-ws-1047-usermodelfact-type-usermodelstore-protoc-1821

+21 core tests, all new and none moved or removed: `tests/memory/user_model/`
covers the new `UserModelFact` record and `InMemoryUserModelStore` (revision
lineage, owner isolation, tombstones; 8 tests) and same-user promotion,
cross-user refusal, reinforcement, contradiction review, correction and
tombstone non-recreation (13 node IDs including parametrized cases) for #1047.
