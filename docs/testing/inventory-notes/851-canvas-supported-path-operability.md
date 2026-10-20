---
inventory-delta:
  packages/maistro-server/tests: +14
---

# #851 Canvas supported-path operability evidence

Makes the shipped `/v2/canvas` surface operable end to end and pins the wiring
that decides it. Three additions, one per seam of the supported path:

- **New `packages/maistro-server/tests/api/test_canvas_supported_path.py` (+7)** —
  the E2E over real PostgreSQL (`MAISTRO_TEST_PG_DSN`-gated, module-scoped
  scratch database): `alembic upgrade head` from empty against the
  authoritative root chain only; design CRUD through the real HTTP routes over
  the real `PgCanvasStore`, wired by the same `_wire_canvas_ability` helper the
  lifespan calls; canonical job admission; retryable failure requeued with
  persisted attempt counts (bounded by `max_attempts`); terminal failure
  visible with a classified (sanitised) error recorded; worker crash → lease
  expiry → reclaim by a restarted worker completing exactly once with no
  duplicate accepted output; lease lost at the retry ceiling terminalized by
  the reaper with `LEASE_EXPIRED_MESSAGE`. Every truth is read back through a
  fresh store instance / the HTTP surface so nothing passes on process-local
  state.
- **`test_canvas.py` `TestOrgScope` (+2)** — the `/v2/canvas` routes now pass
  the authenticated principal as the store's `org_id` (the post-#857 protocol);
  a foreign principal's design reads as absent (404 / empty list) and the
  authenticated org provably reaches the store predicate.
- **`test_main.py` `TestCanvasAbilityWiring` (+5)** — the application lifecycle
  injects the real `PgCanvasStore` over the shared engine when a database is
  configured (asserted through the real `lifespan`, not just the helper), keeps
  the truthful 503 surface when none is, and never replaces an already-composed
  store.

Net: +14 collected node IDs on `packages/maistro-server/tests/api`, including
the only tests that run the shipped Canvas API against the root migration
chain's own schema and a real worker/reaper lifecycle over the real lease
columns.
