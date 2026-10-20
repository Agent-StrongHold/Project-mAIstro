---
inventory-delta:
  packages/maistro-core/tests: +5
---
# 1338-admitter-cancel-compatibility

#1338: #1320 grew the `TaskAdmitter` protocol with `cancel_run`, and
`TaskQueue.cancel` called it unconditionally, so a downstream adapter compiled
against the earlier two-method (`admit`/`record_transition`) shape raised
`AttributeError` on the first cancelled task — a runtime break, because a
`typing.Protocol` is only enforced structurally at type-check time.

Five additions to `packages/maistro-core/tests/tasks/test_attempt_execution.py`,
in the queue's canonical-cancellation section:

- A legacy two-method adapter's *admitted* work (receipt carries a `run_id`)
  cancels as a refusal, not a crash: no `AttributeError`, `False` returned,
  and the receipt stays QUEUED. The queue probes the capability with
  `getattr` — the one repair the issue names as the smaller, non-breaking
  change.
- The same refusal holds for *in-flight* admitted work (receipt at PLANNING),
  and the test proves the queue never launders the refusal through
  `record_transition` as a canonical CANCELLED write either: physical
  cancellation is unavailable, and terminalizing the receipt would make
  "stopped" mean "locally forgotten" (#1242). The refusal is logged
  (`task_cancel_unsupported_by_admitter`) rather than silent.
- Repeat cancel calls under the legacy adapter keep refusing — no delayed
  success, no crash, receipt still open.
- Truly unadmitted work (no admitter wired, `run_id` None) keeps its
  documented receipt-only cancellation and is visibly distinct from stopped
  physical execution: the receipt carries no run identity at all.
- The capable path is pinned unchanged: first cancel wins through the
  canonical Run/Attempt service (Run settles CANCELLED), and the repeat call
  hits the pinned already-terminal contract (`False`) instead of crashing.

The existing no-admitter and capable-admitter cancellation tests were left
untouched; these five hold only the #1338 compatibility boundary.
