---
inventory-delta:
  packages/maistro-core/tests: +62
  packages/maistro-server/tests: +10
---
# m3-98-backlog-item-service

New tests only; nothing was removed or moved.

- `packages/maistro-core/tests` (+62): `workspaces/backlog/test_backlog_store_conformance.py`
  runs the BacklogItem store contract over the in-memory reference and the SQLite
  store (create/get, duplicate ids and external keys, list filters and rank order,
  compare-and-set updates (including a miss at the `UPDATE`'s own `WHERE`), concurrent updates with one winner, refused
  identity/claim fields, cross-Workspace Projects/dependencies/parents, dependency
  and parent cycles with diamonds that are not cycles, restart durability, non-finite ranks, claim fields refused on create, callers getting copies rather than the stored record) plus the Goal reference and BacklogItem validation cases;
  `workspaces/backlog/test_backlog_wiring.py` pins the backend selection; and
  `test_container_wiring.py` gains the memory and `sqlite:` Container wiring cases.
- `packages/maistro-server/tests` (+10): `api/test_backlog_api.py` covers member
  reads, 403 on member writes, 404 for non-members and cross-Workspace ids, 409 on
  a stale PATCH/parent write with the current item, edge endpoints, refused claim
  fields and duplicate external keys, explicit nulls and non-finite ranks as 422, a missing parent as 404, fail-closed without a store, and mounting on
  the production app.
