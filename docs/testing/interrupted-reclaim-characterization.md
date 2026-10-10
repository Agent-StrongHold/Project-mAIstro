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

Exact tested head: `e97c766a7dcc767952d39c9fa1dcefcfbd22848f` on draft PR #1872,
based on `develop@045cfdfbe3eaa0c84493eb02754d7410b0c69378`.

GitHub Actions executed:

```text
uv run pytest packages/maistro-core/tests -v --tb=short
```

The four exact characterization nodes produced:

```text
test_recovery_tick_rediscovers_reclaim_committed_before_reconcile[memory] FAILED
test_recovery_tick_rediscovers_reclaim_committed_before_reconcile[sqlite] FAILED
test_explicit_recovered_reconcile_parks_same_reclaimed_evidence[memory] PASSED
test_explicit_recovered_reconcile_parks_same_reclaimed_evidence[sqlite] PASSED
```

Full core result:

```text
2 failed, 11491 passed, 747 skipped, 1 xfailed
```

Both rediscovery failures are the same contract failure. After the first
Container commits the reclaimed physical Attempt as `CANCELLED` and dies before
logical reconciliation, the fresh public recovery tick leaves the canonical Run
`RUNNING` instead of parking it `WAITING`. The failure is reproduced both
with retained in-memory state under a fresh Container owner and after closing
and reopening the same SQLite database file with a new Container/store.

The physical evidence was already verified before that assertion: the exact
Attempt id was persisted `CANCELLED`, classified by the existing
`is_reclaimed_attempt` predicate, retained its lease/fence and ordinal, and
was reloaded rather than passed from the interrupted call. No fresh Attempt was
created.

The two positive controls pass on those equivalent persisted facts. Reloading
the reclaimed Attempt and explicitly calling
`AttemptLifecycleReconciler.reconcile(..., cancellation=RECOVERED)` parks the
NodeRun and Run as `WAITING` while leaving exactly the same one physical
Attempt. This isolates the gap to **rediscovery by the public recovery tick**,
not the lifecycle's ability to consume known reclaimed evidence.

The intended focused reproduction remains:

```text
uv run --frozen pytest packages/maistro-core/tests/runs/test_interrupted_reclaim_characterization.py -q -ra
```

The draft deliberately remains red. Per #1863, the assertion is not xfailed,
skipped, or inverted, and no production recovery policy is changed in this
proof-only leaf.
