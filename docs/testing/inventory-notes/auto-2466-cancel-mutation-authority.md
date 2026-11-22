---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---

# #2466 Conductor DAG-run cancellation clears the canonical mutation boundary

`routes/dag_runs.py::cancel_run` authorized cancellation with the **read**
seam only (`visible_run_detail`, which admits every Workspace member per
#1152) and then called `RunExecutionService.cancel_run` directly — so an
ordinary peer member could cancel another principal's live Run, and a
projection row in Workspace X delegated cancellation of a canonical Run filed
in Workspace Y. The fix resolves the canonical target and clears the shared
`RunStoreBoundary.require_run_mutation` gate (initiator or Workspace
administrator — the same rule maistro-server's `/v1/runs/{id}/cancel` answers
through, pinned there by
`test_task_workspace_scope.py::test_cancel_stays_with_the_initiator_or_an_administrator`),
then refuses a projection row whose canonical link is filed in another
Workspace (the write-side twin of `_overlay`'s attribution rule). Every
refusal is the seam's no-enumeration 404, raised before any Run/NodeRun/Attempt
transition or provider signal.

+4 collected node IDs on `packages/hive-conductor/backend/tests`
(`test_dag_run_cancel_authorization.py`), each driving the shipped route
handler against a real `InMemoryRunStore` with the provider parked mid-flight
so denial is proven against the physical path (transition spy on
`transition_run` + provider-unwind witness), not merely the response code:

1. member B reads initiating member A's Run but cannot cancel it — 404,
   word-for-word the unknown-id refusal, no durable fence attempted, provider
   never unwound, Run/NodeRun/Attempt untouched;
2. the initiator cancels through the projection id and a Workspace
   administrator (never initiated) through the direct canonical id — both
   physically stop the parked provider — while the peer is refused at every
   altitude between the two successes;
3. a projection row visible in Workspace X linked to a live Run in Workspace
   Y lets neither an X-only caller nor even the Run's own initiator cancel
   through the row, while the initiator's direct canonical id still works;
4. a nonmember outsider and an unknown id are refused identically against the
   canonical Run's own id (regression guard; already true before the fix).

No production file outside `packages/hive-conductor/backend` changes; the
maistro-server cancel route and `RunStoreBoundary` are consumed, not edited.
