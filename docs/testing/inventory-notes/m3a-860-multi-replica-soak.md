---
inventory-delta:
  scripts/: +2
---

# M3-A #860 multi-replica load & concurrency soak harness

Adds `scripts/soak/run_soak.py` and `scripts/soak/nginx-soak.conf` — the
falsification harness defined by `docs/testing/soak/m3a-load-profile.md` and
run for issue #860 (parent #89, M3-A).

What the harness does (no pytest nodes are added or removed; this is a
runnable evidence producer, so the delta is tooling, not collected tests):

- Boots the RC application surface (`maistro_server` via the RC entrypoint's
  exact migration-then-uvicorn path) as two replicas behind an nginx LB that
  mirrors `deploy/nginx.conf` passive-health policy.
- Drives a sustained mixed request profile (readiness/liveness/task
  admission/receipt reads/metrics gate) while sampling RSS, open descriptors,
  PostgreSQL sessions/locks, and canonical spine depth per status.
- Proves exactly-once task admission (concurrent duplicate
  `Idempotency-Key` submissions through the LB), exactly-once schedule
  occurrence claim (two OS processes racing `ScheduleRunAdmitter.admit_due`
  on the canonical PostgreSQL store — the process-level form of
  `packages/maistro-core/tests/scheduling/test_pg_admission.py::
  test_two_admitters_concurrently_claim_each_due_occurrence_once`), rate-limit
  enforcement (LB, direct-replica, authenticated bursts), and SIGKILL/restart
  of one replica mid-load with LB failover and rejoin.
- Emits `evidence/m3a-soak-evidence.json` + `evidence/metrics.jsonl` tied to
  commit/diff/config/image hashes, with mechanical pass/fail against the
  profile thresholds.

Existing pytest inventory is unchanged: the harness reuses the live-Postgres
admission-race pattern already covered by
`packages/maestro-core/tests/scheduling/test_pg_admission.py` (path as on
disk: `packages/maistro-core/tests/scheduling/test_pg_admission.py`) rather
than duplicating it as a unit test; the soak evidence is the deliverable.

## Repair round (2026-09-29, this lane)

Verdict on run 1 stands: **NEEDS-REPAIR and re-soak** — no promotion claim
changes. The round confirmed all six prior findings against this head and
repaired the three harness-side ones:

- F6 (undocumented env): `uv sync --locked --extra dev --dry-run` reports
  `Would uninstall maistro-server` → harness now pins
  `uv run --package maistro-server` (clean-env check: 91 packages installed,
  `maistro_server.entrypoint.run_migrations` imports OK); harness's own
  `run_migrations()` executed OK against the soak DB.
- Boot-failure orphan: `boot_stack`/teardown now `killpg` + fail loudly if a
  replica port still accepts connections.
- Claim gate: due occurrence pinned to the most recent hourly instant;
  `phase_claim_probe` verifies per occurrence against the durable
  `(schedule_id, scheduled_for)` claim. Live two-process rerun: 1 Run,
  loser `already_fired`, SQL 1 occurrence × 1 run, `ok=true`.
- F7 (production, filed not fixed here): concurrent-boot
  `CREATE INDEX IF NOT EXISTS idx_learnings_scope` race reproduced against
  pinned pg18 (`duplicate key value violates unique constraint
  "pg_class_relname_nsp_index"`); must be fixed before the promotion soak.

No pytest nodes added or removed; deltas remain `scripts/soak/` tooling and
evidence prose.
