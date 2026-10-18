---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-147 receipt/attempt-identity repair

Repairs the #147 verification finding that the delegation child's
reservation-time yielded Attempt recorded `task_id: ""` — a placeholder for a
fact that did not exist yet — and stayed that way after the real receipt was
attached, while the receipt itself lived only in the Run's post-admission
provenance. Reconciled against [ADR-082526-7f02](../../adr/ADR-082526-7f02-dispatch-identity-belongs-to-the-attempt.md):

- **AC-3 ("an absent fact stays absent")**: the child Run is now reserved with
  no receipt key at all rather than `a2a_task_id: ""`, and the yielded
  transport Attempt's evidence names the delegation mode only. The receipt is
  attached once, after transport acceptance, via `attach_delegation_receipt`.
- **AC-1's pattern (dispatch identity belongs to the Attempt)**: the settling
  (completed) Attempt's evidence carries the `task_id` under the same key the
  Run's provenance and the A2A answer use; an answer that names no receipt
  records its absence instead of a placeholder. Yielded Attempts stay terminal
  evidence and are never amended.
- **Issue text reconciled, not weakened**: #147's acceptance puts the A2A
  `task_id` on the child Run's provenance as a receipt; it stays there. The
  ADR governs where *dispatch identity* is readable, and the settling Attempt
  now satisfies it rather than the Run being the only record.

Collected nodes added to
`packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_child_run.py`
(class `TestTheReceiptIsAttemptOwnedIdentity`):

- `test_the_reservation_attempt_records_no_receipt_placeholder`
- `test_the_settling_attempt_names_the_transport_receipt`
- `test_an_answer_without_a_receipt_records_no_placeholder`

Also updated in place (no node-count change):
`test_a_submitted_peer_response_without_a_receipt_pauses_for_reconciliation`
now asserts receipt *absence* on a not-yet-reconciled child instead of the old
empty-string placeholder.
