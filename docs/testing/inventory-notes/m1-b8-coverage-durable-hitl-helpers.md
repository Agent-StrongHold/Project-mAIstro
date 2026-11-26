---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/hive-conductor/backend/tests: +16
---
# m1-b8-coverage-durable-hitl-helpers

Coverage gate repair for #2420 / M1-B8 durable inbox approval: lift
changed-line coverage on the three files that were below the 90% floor.

- `test_durable_hitl_approval.py` **+8**: READ-tier / blank scope / missing
  ApprovalStore refusals; approved policy path; `_InfraApprovalNode` executor
  (incl. non-infra TypeError and non-mapping result); production
  `execute_approved` with `approved=True` + legacy `act()` TypeError fallback;
  unknown node_id KeyError; non-PAUSED admission RuntimeError.
- `test_capabilities_wiring.py` **+6**: Hive default Workspace HITL scope
  resolution + fail-closed; approval run-status reads; admittor requires
  graph_run_store; admittor parks via admit + resolve_provider; resolve_provider
  fail-closed (binding down / redirect / missing infra).
- `test_hitl_durable_approval.py` **+10**: missing expected id; ApprovalStore
  unavailable; non-approver authority; approval mismatch; paused NodeRun
  cardinality; get/resolve error translation; ValueError fence before resolve;
  malformed pause maps; durable-pause metadata None branch.
