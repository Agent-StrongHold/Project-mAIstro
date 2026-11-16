---
inventory-delta:
  packages/maistro-core/tests: +0
---

# 105 integration-scope: tolerate transient checks-API failures (+2 node tests)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

CI-repair round for #105's merge-queue blocker. `integration-scope` (run
37155659880, job 111298400951) failed on candidate dd533927d even though
**all nine required specialized producers concluded success** on that SHA:
the aggregator's `github-script` poller crashed when one
`checks.listForRef` call hit a GitHub 5xx ("No server is currently available
to service your request"), 12 minutes into its 85-minute evidence window. A
single transient API error outweighed every green producer.

Repair: the poll loop now treats a failed listing like any other pending
state — log a warning, sleep, retry — inside the *same* polling budget, so
the window is not extended and an API that stays down for the whole budget
still fails closed with the unchanged `timed out waiting for required
specialized CI evidence` verdict. A required check's own bad conclusion
still fails immediately; only the *listing* call is retried.

`packages/maistro-core/tests` delta is **+0**: the tests live in
`tests/ci/integration-scope.test.cjs`, which `ci.yml` runs with
`node --test` — it is not a pytest suite, so the recorded inventory is
untouched. The two added node tests execute the shipped script body in a VM
(the file's existing harness) with an API that throws the run's exact 503
body:

- recovery: two transient failures then a green snapshot → the aggregator
  succeeds, burns 3 of its attempts, sleeps between them, and warns with the
  API error text;
- fail-closed: the API down for the whole budget → the timeout verdict, not
  a crash and not a pass.

Both fail against the pre-repair script (the thrown error propagates out of
the script body unhandled — the run 37155659880 failure mode) and pass
against the repaired one; the eight pre-existing tests still pass, pinning
that newest-attempt resolution, verdict handling, and the 170×30 s budget
are unchanged.
