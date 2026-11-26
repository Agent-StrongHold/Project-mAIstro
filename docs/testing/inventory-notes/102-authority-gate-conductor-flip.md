---
inventory-delta:
  packages/maistro-core/tests: +3
  tests/: +6
  packages/hive-conductor/backend/tests: +4
---

# Authority gate, store conformance extension, and the Conductor flip (#102)

Three smaller deltas for the #102 cutover's remaining surfaces:

- `tests/test_backlog_authority_gate.py` is new (+6): under db authority the
  consistency gate requires the generated banner and the recorded export
  digest, so a direct hand edit to the generated `BACKLOG.md` fails with
  "not authoritative"; under markdown authority (or with no marker at all)
  behavior is unchanged; the shipped marker is the pre-cutover default.
- `packages/maistro-core/tests/backlog/test_backlog_store_conformance.py`
  (+3, one body over the memory/SQLite/PostgreSQL parameterization): the
  migration fields (`dependencies`, `BacklogOrigin`, `priority`, `rank`)
  round-trip through every backend including a durable restart, and
  stale-version dependency edits stay refused.
- `packages/hive-conductor/backend/tests/test_backlog_authority_flip.py` is
  new (+4): the authority statement in every list/detail payload flips
  machine-readably to `ui_authoritative: true` under a recorded db authority
  and never flips on from an unreadable marker; and the HTTP backlog surface
  works against SQLite persistence — create/edit survive a simulated restart
  (fresh store over the same database) with the 409 stale-version contract
  intact.

One existing test was updated in place, not removed or renamed:
`test_backlog_routes.py::test_list_and_detail_carry_the_non_authoritative_marker`
now asserts the extended five-key authority statement (the #102 fields
`authority` and `authority_revision` join the #99 marker); its pre-cutover
assertion (`ui_authoritative is False`) still holds against the shipped
revision-0 marker.
