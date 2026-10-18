---
inventory-delta:
  packages/maistro-server/tests: +1
---

Issue #1828: `POST /tasks` translates the canonical admission backpressure into
HTTP 429. One test added to
`packages/maistro-server/tests/api/test_tasks_run_identity.py`:

- `test_task_submission_at_capacity_returns_429_without_retained_claim` — the
  spine is wired through `wire_execution_spine` with a tightened
  `RunConcurrencyLimits` (the wiring's operator-facing configuration path, not a
  stub), one task is admitted through the ASGI route, and the next submission is
  refused by the real `RunStore.create_run` ceiling. Asserts the route answers
  429 with `Retry-After` (the chat turn convention from
  `maistro.runs.chat_refusal`), no `Location`, and no receipt shape on the body;
  that the queue holds no new receipt, the Run store holds no new QUEUED Run,
  and the idempotency claim tier holds no row under the refused key
  (`admission_scope_key` + `store.get`); that a replay of the already-admitted
  key still returns the original receipt while saturated without admitting
  again; and that after the admitted root terminalizes through the canonical
  cancel path, the previously refused key is accepted as a fresh admission with
  its own Run.

Fail-before/pass-after evidence: against the unmodified route the test fails
with `RunConcurrencyExceeded` propagating out of `RunStore.create_run` through
the handler; with the translation added it passes; removing the
`RunConcurrencyExceeded` clause makes it fail again. No production baselines
changed — the 8-per-principal / 32-per-Workspace ceilings and the queue's
admission/idempotency/cleanup behavior are untouched (`test_tasks_idempotency.py`
passes unchanged).
