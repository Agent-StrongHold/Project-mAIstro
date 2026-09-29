---
inventory-delta:
  scripts/: +2
  docs/testing/soak/evidence/: +4 (repair-round validation artifacts, not collected tests)
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

### Mini soak at the repair head (functional validation, NOT promotion evidence)

`--sustain-seconds 120 --rps 4 --workers 4` on a clean tree at the repair
commit, evidence in `evidence/m3a-repair-validation*.json|.log` (120 s ≪ the
4 h minimum; this run validates the harness, it does not sign the RC):

- Repairs live: real SIGKILL failover (killed → rejoined in 15 s, vs run 1's
  <1 s no-op), `rate_limit_enforced=true` on the `/tasks` probe,
  `exactly_once_schedule_occurrence=true` (per-occurrence gate),
  `hashes.git_clean=true`.
- F3 reproduced unchanged (1671/2271 sustained requests = 502 through the
  LB while all phase/burst requests succeed) — still the promotion blocker.
- New gate observation, handled: `exactly_once_task_admission` failed
  strictly because 4/6 duplicate submissions got LB 502s while the 2
  delivered agreed on one run_id — exactly-once unproven under the storm,
  not falsified; the phase now records `delivered` + `cause` so run 2 can
  tell transport degradation from a duplicate (gate strictness unchanged).
- Teardown left no orphans (replica/LB ports free after exit).

No pytest nodes added or removed; deltas remain `scripts/soak/` tooling and
evidence prose.
