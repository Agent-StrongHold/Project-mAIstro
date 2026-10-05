---
inventory-delta:
  packages/maistro-core/tests: +26
---
# 1898-capability-approval-continuation

Extends `invoke_capability_effect` (#1898, parent #1192) with keyword-only
optional continuation arguments — `continuation_metadata`, `resume_at`,
`request_digest` — so a node pausing on `InvocationApprovalPending` can retain
a fixed continuation, deadline and request digest on the canonical
`awaiting_human_approval` pause. Omitting all three preserves the previous
two-key pause shape exactly; the existing default-flow test is unchanged.

New tests:

`packages/maistro-core/tests/graph/nodes/test_capability_hitl.py` (+21) —
helper-level and node-level coverage:

- Default shape preserved when continuation arguments are omitted (exact pause
  metadata key set, `resume_at is None`, resume still completes).
- Pending approval retains the exact approval receipt (canonical
  `approval_request_id` from the store), the caller's request digest of the
  exact immutable request, nested continuation metadata, and the fixed aware
  deadline verbatim; two Attempts of the same NodeRun make one physical
  provider call and raise exactly one `approval_required` event.
- Continuation metadata is copied before the operation runs: mutating nested
  mapping/list values and injecting top-level keys after helper entry cannot
  change the persisted pause metadata.
- Frozen Graph JSON input (`GraphExecutionState` metadata, i.e.
  `MappingProxyType`/tuple containers that `copy.deepcopy` cannot handle) is
  accepted and thawed to ordinary JSON containers — the fixture proves
  `deepcopy` raises `TypeError` on it.
- Each reserved top-level key (`paused_reason`, `resume_at`,
  `replay_effect_key`, `approval_request_id`, `effect_key`, `request_digest`)
  fails with `ValueError` before the operation is awaited.
- Invalid request digests (wrong length, non-hex, uppercase, empty, non-string)
  fail before the operation is awaited.
- Naive datetimes, non-datetime values, and a `tzinfo` whose `utcoffset()` is
  `None` fail before the operation is awaited.
- A changed request digest and a denied approval are refused by the existing
  governed authority (`InvocationDenied`), never converted into a completion;
  the provider is not called.

`packages/maistro-core/tests/graph/durable_runs/test_capability_pause_metadata.py`
(+3) — real durable Graph path: the parked Run is `RunStatus.PAUSED` (a human
pause), never `WAITING`; the persisted pause entry carries the receipt, digest,
continuation and fixed deadline; resuming after `ApprovalStore` resolution plus
`submit_hitl_answer` completes with one physical provider call and no new
approval request; a denied approval fails the run without a provider call. The
approval is resolved directly on the store — production HITL-to-DurableApproval
linkage is the separately owned #55 integration and is not claimed here.

Mutation-checked: the new tests fail when the helper drops the thaw/independent
copy, accepts reserved keys, skips digest-shape checks, re-derives or drops the
deadline, accepts a naive deadline, or stamps a non-human pause reason (the
durable run then parks `WAITING` instead of `PAUSED`).

No production behavior changed for existing callers; the helper remains a pause
adapter and does not resolve approvals, invent principals, or bypass
provider/policy authority.
