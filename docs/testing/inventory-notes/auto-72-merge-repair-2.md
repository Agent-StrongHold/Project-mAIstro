---
inventory-delta:
  packages/maistro-server/tests: +1
---

# auto-72 merge repair 2 (develop 20e6cd4a7 health reconciliation fallout)

The first develop-sync resolution (eafa4cd0e/f9cd3e8ff) kept this branch's
`health.py` while taking develop's deletion of `schemas.HealthResponse` and
develop-side health tests, leaving a production ImportError
(`cannot import name 'HealthResponse' from 'maistro_server.api.schemas'`) that
failed CI collection of `test_health.py`, plus an unreviewed regression: the
merged `/health/ready` served the full detailed payload (checks, policy,
strike backends, persistence) to every anonymous caller, discarding develop's
#1457/#365 admin gate.

Reconciliation preserves both contracts:

- `GET /health` is the minimal public liveness response `{"status": "ok"}` —
  no service/version/uptime on the public path; `HealthResponse` stays deleted
  from `api/schemas.py` (develop already pruned it as dead, matching the
  earlier `ad5e2e4df` fix on the #365 lane).
- `GET /health/ready` restores develop's `_admin_diagnostics_authorized` gate:
  anonymous / user-scope / auth-disabled callers get status-only
  `{"status": "ok"}` / 503 `{"status": "not_ready"}`; admin-scoped callers get
  the detailed payload which now carries this branch's #72 durability facts —
  `strike_tracker.durable` and the `persistence` per-store-family backend
  map (including the write-behind usage-log mode and the pathless
  `sqlite://` memory-backed caveat) — so "health reports actual
  backend/durability" stays satisfied for operators without widening public
  surface.

`test_strike_tracker_health.py` (+1 net): the three backend/durability
readiness tests now probe with an admin bearer token (`ops:admin:...` key)
against auth-enabled settings, and a new test pins that anonymous probes get
the status-only contract with `strike_tracker`/`persistence` absent from the
body entirely.

Re-proof: `pytest` on the exact previous CI failure list (106 passed, 3
skipped), the full `packages/maistro-server/tests/api` suite (392 passed;
408 under coverage), `tests/api/test_health.py` + metrics suites (45 passed),
`ruff check .` and `ruff format --check .` clean,
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exit 0 (1404 reviewed identities, no amendment
needed), mypy on maistro-server src strictly improved (81 -> 80 errors, none
new), and the diff-coverage gate (`scripts/check-diff-coverage.py --base
20e6cd4a7`) re-run with both producers CI uses — the unit producer plus the
`coverage-postgres` job's exact suite list against a real pgvector/pg17
(alembic chain to head, 4262 passed, 8 skipped, `MAISTRO_REQUIRE_PG_LEGS=1`)
— exits 0: every measured changed file is at or above 90% lines / 80%
branch arcs, including `PgElevationStore`'s PostgreSQL legs. Without the
PostgreSQL producer the gate had scored `elevation_durable.py` at 77.4% —
an unmeasured-not-untested artifact, not a defect.
