---
inventory-delta:
  packages/maistro-core/tests: +4
---
# auto-147 interrupted-admission repair

The #147 verification pass (job 418751f66fdd4ba699abde2f18b3662c, verdict
NEEDS-REPAIR) fault-injected the delegation child's creation and found two
defects, both now fixed and both now covered by the four nodes added to
`packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_child_run.py`
(class `TestInterruptedChildAdmission`):

1. `_reserve_child` caught every child-creation exception and adopted whatever
   Run row existed under the delegation key — including this process's own
   half-written child. The parent then paused on a child with zero NodeRuns,
   a shape no resumed answer could settle. Adoption now completes the child's
   canonical evidence (`_ensure_child_evidence`) before the child is relied
   on, and a *persistent* store fault fails the dispatch loudly instead of
   pausing.
2. The child was admitted `QUEUED` before its NodeRun/Attempt evidence. A
   death in that window left a QUEUED Run reading as admitted work while
   `a2a_delegation` is deliberately not a consumable source
   (ADR-082426-6201) — unrecoverable by construction. The child is now
   admitted `CREATED` (the recovery model's resting state for projections)
   and reaches WAITING only through its yielded transport Attempt; the next
   dispatch through the node is the recovery path that finishes an
   interrupted reservation.

Collected nodes added:

- `test_agent_delegate_remote_child_run.py::TestInterruptedChildAdmission::test_a_transient_fault_during_evidence_writing_is_healed_before_the_pause`
- `test_agent_delegate_remote_child_run.py::TestInterruptedChildAdmission::test_a_persistent_fault_fails_the_dispatch_loudly_without_pausing`
- `test_agent_delegate_remote_child_run.py::TestInterruptedChildAdmission::test_a_crashed_replicas_partial_child_is_completed_and_answerable`
- `test_agent_delegate_remote_child_run.py::TestInterruptedChildAdmission::test_the_child_row_is_admitted_created_and_only_parks_with_evidence`
