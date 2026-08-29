---
inventory-delta:
  packages/maistro-core/tests: +7
---
# claude-issue-624-checkpoint-version-drift-3c8e

`packages/maistro-core/tests/orchestrator/waves/test_recovery_compatibility.py`
(+7, new). Nothing deleted or moved. The existing
`tests/tasks/test_checkpoint_replay.py` keeps every case it had, including the
one that locks in "a malformed payload raises rather than silently corrupting
resume state" — that contract is deliberately preserved by the fix below rather
than traded away.

Six criteria and one control:

- **version drift** (AC-1, AC-2) — a checkpoint recorded under a different
  recipe version, and one under a different code registry version, are not
  resumed, and the refusal names both the recorded and the running value;
- **the other side** (AC-3) — a matching checkpoint still recovers, asserted
  with a runner that raises if any wave re-runs, so a check that refused
  everything would fail here rather than pass everywhere;
- **quarantine** (AC-4) — a task recovered past the limit refuses, and a task
  with *no* checkpoints is never quarantined, because "nothing to recover" and
  "stop recovering this" call for opposite actions and a gate that confused
  them would refuse fresh work;
- **partial recovery** (AC-5) — an interruption with no completion marker
  reports the open tool call, pending gate and spend it left, which was
  previously invisible; and the ensemble's own checkpoints can be folded at
  all, which they could not: `replay` read `payload["wave_id"]` while the
  ensemble writes `wave_ids` on its task-level markers, so folding a real run
  raised `KeyError`. Two halves of ADR-056 that shipped without being run
  against each other.
- **events** (AC-6) — carried by the drift and quarantine tests, since a
  recovery decision that cannot be told from a fresh run is not inspectable.

Mutation-verified, four ways: skipping the version check fails AC-1 and AC-2;
never quarantining fails AC-4; dropping the partial-recovery event fails AC-5;
and folding task-level markers as if they were per-wave records fails three
tests with the `KeyError` this change removed.
