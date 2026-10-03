# Interrupted reclaim characterization (#1863)

## Scope

This proof isolates one recovery boundary: the physical lease sweep commits a
reclaimed Attempt as `CANCELLED`, the process stops before the Container can
perform its first logical reconciliation, and a fresh Container later invokes
only the public `recover_abandoned_attempts` tick.

No production recovery policy or implementation is changed here.

## Candidate

- Base: `develop@045cfdfbe3eaa0c84493eb02754d7410b0c69378`
- Test: `packages/maistro-core/tests/runs/test_interrupted_reclaim_characterization.py`
- Backends: in-memory owner recreation and file-backed SQLite close/reopen
- Injection seam: wraps the real `RunStore.reclaim_expired_attempts`; the real
  reclaim returns a committed `CANCELLED` Attempt, then the wrapper raises
  `BaseException` before the Container receives that returned list and before
  any `AttemptLifecycleReconciler.reconcile` call.

The in-memory leg is owner-recreation evidence only. The SQLite leg closes the
first Container/connection and reopens the same file through a fresh Container.

## Exact nodes

- `test_recovery_tick_rediscovers_reclaim_committed_before_reconcile[memory]`
- `test_recovery_tick_rediscovers_reclaim_committed_before_reconcile[sqlite]`
- `test_explicit_recovered_reconcile_parks_same_reclaimed_evidence[memory]`
- `test_explicit_recovered_reconcile_parks_same_reclaimed_evidence[sqlite]`

## Assertions

Both paths create a real Run -> NodeRun -> Attempt lineage, move Run/NodeRun/
Attempt to RUNNING, attach a finite lease, expire it deterministically from the
persisted `expires_at`, and call the real reclaim implementation.

The rediscovery assertion requires the fresh public recovery tick to park the
Run and NodeRun as `WAITING` while preserving the exact reclaimed Attempt,
its id, ordinal, lease/fence, result/error evidence, and one-Attempt count.
A repeated tick must make no further change.

The positive control reloads the same persisted reclaimed Attempt after owner
recreation/reopen and explicitly calls
`AttemptLifecycleReconciler.reconcile(..., cancellation=RECOVERED)`. It must
park the same Run/NodeRun without creating or dispatching a new Attempt.

## Execution

Exact-head CI execution and fail/pass output will be recorded here after the
draft PR runs. The intended focused command is:

```text
uv run --frozen pytest packages/maistro-core/tests/runs/test_interrupted_reclaim_characterization.py -q -ra
```
