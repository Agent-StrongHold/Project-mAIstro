---
inventory-delta:
  packages/maistro-canvas/tests: +4
---
# auto-735-canvas-lease-coverage

Four new unit tests in `packages/maistro-canvas/tests/test_canvas_store_job_lease.py`
close a diff-coverage gap the #1294 Canvas canonical-execution merge left in
`PgCanvasStore.claim_next_pending`/`reap_expired_leases`: the non-positive
`lease_seconds` rejection, the empty-queue `None` return, the defensive
`JobNotFoundError` when a claimed row's detail row is missing, and the
zero-rows-reaped commit-and-return-`[]` path. All four use a fake
`AsyncSession` rather than a real Postgres connection, so no other suite's
count moved.
