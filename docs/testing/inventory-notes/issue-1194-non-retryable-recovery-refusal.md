---
inventory-delta:
  packages/maistro-core/tests: +1
---
# issue-1194-non-retryable-recovery-refusal

Closes the re-flagged verifier finding against
`attempt_executor._reconcile_orphaned_attempts`/`execute_one`: recovery
cancelled an orphaned Attempt and re-dispatched the NodeRun without consulting
`ReplaySemantics`. The earlier round's defense — a reproduction showing
`calls == 1` across `['cancelled', 'completed']` — only proved the synthetic
crash happened *before* the node body ran; a crash *after* the effect started
would re-execute it, which is acceptance criterion 7's "blindly auto-retried
after an ambiguous physical effect".

## The repair

`execute_one` now derives the node's `ReplaySemantics` once and treats a
non-COMPLETED Attempt tail as interrupted physical history. When the contract
is NON_RETRYABLE, the fresh recovery Attempt still rotates per
ADR-082826-08f0's orphan row (CANCELLED with RECOVERED, fresh chronological
Attempt), but its executor records a `ReplayRefused` NodeResult as the
Attempt's own durable evidence instead of invoking the node body. The fold's
existing exhausted-failure rule — which already consumes this same contract via
`_may_revisit_after` — fails the Run with `ReplayRefused`, putting the
ambiguity in front of a person (the explicit new-work path).

ADR reconciliation, recorded: the ADR's disposition table governs the physical
lifecycle (never strand work, never steal live work, never rewrite history) and
its "retry rotates to a new Attempt" row is honored — the rotation happens. The
replay contract governs whether the *effect* may repeat; for NON_RETRYABLE work
it may not, so the rotated Attempt settles the refusal rather than a second
execution. All ADR fixed points still hold: history preserved, repeated
recovery idempotent (a FAILED Run refuses recovery), canonical seam only.

## New test

`test_resume_never_reexecutes_a_non_retryable_nodes_ambiguous_effect`
(packages/maistro-core/tests/graph/durable_runs/test_attempt_executor.py):
resumes a record whose NON_RETRYABLE node holds a RUNNING orphaned Attempt and
one pre-crash effect call; asserts the call count stays at one, the attempt
rotation is `['cancelled', 'completed']`, the fresh Attempt's evidence names
`ReplayRefused`, and the Run/NodeRun fail with the refusal error — no second
execution, ambiguity surfaced.
