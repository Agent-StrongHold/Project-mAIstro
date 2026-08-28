---
inventory-delta:
  packages/maistro-core/tests: +9
---
# claude-m1-462-recovery-disposition-3173

Nine new tests for the interrupted-Run recovery disposition seam (#462, #338,
ADR-082826-08f0), purely additive:

- 4 in `tests/test_container_chat_runs.py` — chat admission failure injection at
  each lifecycle hop: the stranded QUEUED/CREATED Run is compensated to
  CANCELLED/`admission_incomplete`, the turn is still answered, repeated
  compensation is idempotent, and a mid-admission client disconnect both
  compensates (shielded) and propagates.
- 4 in `tests/graph/durable_runs/test_recovery_disposition.py` — resume refuses
  a demonstrably live-leased Attempt; a lapsed lease recovers through the lease
  seam; repeated orphan reconciliation is idempotent; a mid-Attempt restart
  against a SQLite store across a real reopen produces the documented
  disposition (CANCELLED history + fresh Attempt + COMPLETED Run).
- 1 in `tests/test_container_wiring.py` — the recovery tick parks the reclaimed
  Attempt's NodeRun and Run through the reconciler and refreshes the
  non-terminal-Run gauges; a second tick is a no-op.
