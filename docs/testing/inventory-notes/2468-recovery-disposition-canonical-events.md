---
inventory-delta:
  packages/maistro-core/tests: +9
---
# #2468 — abandoned-Attempt recovery dispositions persist through the canonical EventEnvelope

Nine maistro-core node IDs join `packages/maistro-core/tests/runs` with the
#2468 wiring that injects the composition root's
`CanonicalRecoveryEventSink` into both production recovery halves
(`_reclaim_abandoned_attempts` and `_reconcile_unreconciled_terminal_attempts`).

Eight arrive in `test_recovery_event_seam.py`, service-free and therefore
measured by the `coverage (no services)` producer:

- the seam-selection table on the real Container: the composition sink is
  returned while its Run store is live; a crash-window replica that swaps the
  Run store re-binds through the same canonical publisher; a hand-built
  Container with a stale sink but no publisher keeps that sink; one with no
  canonical authority at all keeps its bare legacy bus. The last two close
  the exact diff-coverage gap the first CI round reported (uncovered
  `container.py` lines in the fallback branches).
- the sweep persists the recovery disposition canonically *before* the legacy
  bus observes it, with full Workspace/Project/Run/NodeRun/Attempt
  correlation and the persisted identity attached to the legacy projection —
  doubling as the #2468 negative oracle: a wiring regressed to
  `events=self.event_bus` mints no canonical envelope and fails these
  assertions.
- retry sweeps and replica re-announces cannot mint a second Workspace
  sequence or re-fire the legacy trigger (deterministic event_id, dedupe on
  append, projection only on insert).
- a canonical append failure raises through the sweep (nothing claims
  durable success), delivers no legacy fact, leaves the physical disposition
  settled and inspectable, and reconciles idempotently once the store heals.
- an interrupted reclaim (physical CANCELLED+RECOVERED committed, logical
  reconciliation lost) is rediscovered by the replay half (P5a) and announced
  through the canonical store, not only on the bus.

One arrives in `test_pg_recovery_disposition_events.py`, gated on
`MAISTRO_TEST_PG_DSN` and executed by the `coverage (PostgreSQL)` producer
against the migrated chain: on a supported PostgreSQL Container the sweep
lands exactly one `run.recovery_disposition` envelope row, a replica
reopening the same database observes the same event_id at the same sequence,
and a replica re-announce inserts nothing.

No suite loses a count; no other package's tests moved.
