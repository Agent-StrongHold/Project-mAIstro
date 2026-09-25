---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +6
---
# #1108 — refuse unadmittable chat turns with a retryable 503

Owner decision 2026-09-23 amends ADR-082326-c126: a chat turn that cannot get
its canonical Run is refused and never dispatched.

- `packages/maistro-core/tests` +2: in `test_container_chat_runs.py` the two
  no-refusal tests (`test_the_turn_is_answered_even_when_admission_fails`,
  `test_no_chat_admitter_means_no_run_id_and_no_failure`) were inverted into
  refusal tests, and four were added — a Run adopted with no Run store is
  refused; a pre-dispatch `RunIntegrityError` (vetoed Attempt create) is
  refused with zero dispatches (the mutation check: restoring
  `return await dispatch()` fails it); a pre-dispatch driver error is refused
  too; and a `RunIntegrityError` raised by the dispatch itself is *not* turned
  into a retryable refusal (the model was reached). The #338 compensation tests and the
  four no-refusal cases and the raw pre-dispatch store-failure case in
  `runs/test_chat_execution.py` were inverted in place (no count change).
- `packages/maistro-server/tests` +6: `test_no_chat_admitter_means_a_null_run_id...`
  was replaced by parametrized (stream false/true) 503 + Retry-After tests
  for a broken admitter and for no admitter (4 cases), plus a compensated
  QUEUED-transition failure, a non-stream pre-dispatch spine refusal, and a
  streamed one that emits an `unavailable` SSE event (net +6).
