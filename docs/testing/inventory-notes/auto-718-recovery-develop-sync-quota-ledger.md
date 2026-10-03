inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
  packages/maistro-server/tests: +0
---
# auto-718-recovery-develop-sync-quota-ledger

Repair round for the #718 lane: tree recovery, develop sync, and
re-validation of the canonical Invocation quota-ledger contract. No tests
were added or removed by this round (deltas are zero); every suite below is
recorded evidence, not new inventory.

## What this round actually changed

1. **Recovery.** The previous round left HEAD `9d306e325` with unresolved
   conflict markers in `maistro/container.py` and
   `maistro-server/tests/api/test_main.py` (a driver salvage commit of a
   half-merged tree), and the worktree reverted to the pre-merge state after
   an "orphan rebuild apply" failed mid-patch. The resolved integration
   survived only in the git index (tree `c61a7b1a`). This round materialized
   that tree (`recover:` commit `09dbcc885`), after hash-verifying that all
   25 stale untracked files were byte-identical pre-merge copies.
2. **Develop sync.** Merged `origin/develop` (257e1d992, then its successor
   053f93969) into `auto-718`, resolving 18 conflicted files in place
   (merge commits `265e70cab`, `cb143d8c8`). The #718 seams survived the
   merge untouched: `CanonicalInvocationUsageRecorder` stays installed as the
   Invocation `on_completed` hook by all three effect-context backends
   (`capabilities/effect_context.py`), the Container still passes the usage
   log/quota tracker, and `041_quota_invocation_evidence` stays in the single
   linear migration chain (head `050`).

## Re-validated #718 evidence (all on the merged tree)

- Recorder + exactly-once/retry-repair/missing-usage:
  `packages/maistro-core/tests/quota/test_canonical_invocation_recorder.py`
  (6 tests), `tests/quota/test_tracker.py`
  (`test_record_invocation_missing_usage_is_unreported_not_zero`).
- Governed model call moves the ledger once, keyed to the canonical
  Invocation id: `tests/capabilities/test_model_chat_egress.py::
  test_canonical_invocation_completion_records_quota_once`.
- Ledger-write failure surfaced, then repaired on deduplicated replay
  without double charge: `tests/capabilities/test_binding_invocation.py`
  (FlakyLedger case).
- Conductor raw-gateway fallback: reported usage with provenance, missing
  usage as unreported marker, governed egress leaves NO fallback evidence
  (no double counting), failing ledger never takes down the call:
  `tests/agents/test_conductor.py` (7 quota cases).
- Verifier outage -> unavailable evidence + `reconciliation_errors_total`
  metric, never an exception out of `maybe_reconcile`; mismatch ->
  `reconciliation_mismatches_total` + warning + policy `record_mismatch`:
  `tests/quota/test_reconciliation.py`.
- Explicit-verifier half remains explicitly retired/owed, recorded in
  `quality/reachability-dispositions.json` id `quota-verification`; the
  ambient `on_response` hook is documented as a compatibility adapter with
  no shipped production supplier (`quota/recorder.py` module docstring).

## Suite evidence this round (merged tree)

- `packages/maistro-core/tests`: 11419 passed, 782 skipped.
- `packages/hive-conductor/backend/tests`: 3274 passed, 6 skipped.
- `packages/maistro-server/tests`: 481 passed, 9 skipped.
- evolve/rsi/canvas/turing: 2222 passed (swebench needs
  `DOCKER_HOST=unix:///run/user/1000/docker.sock`).
- root `tests/`: 4296 passed (includes branch-independence, gates,
  installer suites).
- PostgreSQL legs (pg18 container, clean schema migrated `alembic
  upgrade head` -> 050): persistence + migrations 736 passed;
  scheduling + effect-context convergence + elevation-durable 321 passed —
  including `quota_invocation_evidence` round-trips on real Postgres.
- Ratchet gates at merge-base 053f93969: radon 145 -> 145 (0 new/0
  regressed/0 stale), vulture 1361 -> 1361 (0 unclassified), reachability,
  suite inventory, merge markers, convergence matrix all OK.
