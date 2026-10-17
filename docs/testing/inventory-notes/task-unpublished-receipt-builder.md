---
inventory-delta:
  packages/maistro-core/tests: +5
---

# task-unpublished-receipt-builder

Issue #1866 extracts the pre-admission `TaskResponse` constructor from
`TaskQueue._submit_once` into one pure, synchronous helper without changing
publication or canonical Run admission.

The five focused nodes characterize full/default field parity, owner precedence,
the supplied idempotency-key and constraint-copy contract, absence of builder
side effects, and the real `_submit_once` ordering. The ordering test blocks
the admitter to prove the receipt is still unpublished while admission is in
flight, then verifies the canonical `run_id` is attached before persistence,
pending notification, and counters. Its refusal arm proves an admission
exception still publishes nothing.
