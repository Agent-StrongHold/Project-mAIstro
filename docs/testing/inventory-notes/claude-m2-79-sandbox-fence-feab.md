---
inventory-delta:
  packages/maistro-core/tests: +18
---
# claude-m2-79-sandbox-fence

#45 fenced the canonical store, and that fence stops at the process edge. A
sandboxed worker is a different process — by #76 sometimes a different kernel —
so everything it publishes crosses a boundary the store has never seen (#79).

**`tests/sandbox/test_fence_across_boundary.py` (+18)**

*What crosses, and what does not.* The fence carries the Attempt, the NodeRun,
the lease epoch and the token, and deliberately not the lease's `holder`,
`issued_at` or `expires_at`. Acceptance asks that the sandbox receive "only the
current fence identity needed for its work": `holder` is operational topology,
and the timings invite a sandboxed process to judge its own validity, which is
the decision the fence exists to take away from it. A partial fence reads as no
fence rather than a weaker one.

*Staleness, in each way it happens.* The important one was found by a failing
test rather than by design. **Reclaiming an expired lease does not clear the
lease** — it cancels the Attempt and leaves the token in place. A worker whose
lease lapsed therefore comes back holding a token that still matches, and the
first draft of the guard, which compared tokens and checked for a missing
lease, waved it straight through. Terminal status is now checked first, and it
is the check that actually catches the case the issue is about. The other three
— Attempt gone, newer lease, moved epoch — are the ordinary ones.

*The door, and the side effect behind it.* `fenced_commit` asserts before it
publishes, and one test asserts the publish never ran, because checking
afterwards would be a report of the failure rather than its prevention. Two
race tests play the sequence out in order: a slow worker reclaimed mid-flight,
and two workers where exactly one holds the current lease and the store — not
whichever finishes first — decides which.

*Backend independence.* The fence is adjudicated against the canonical store,
so a fake-backed sandbox and a bubblewrap-backed one are refused by the same
rule. A backend that could weaken this would be a backend deciding its own
containment.

One vulture entry was pruned rather than banked: `ExecutionLease.lease_epoch`
was carried in the model and read by nothing until this fence consulted it.
