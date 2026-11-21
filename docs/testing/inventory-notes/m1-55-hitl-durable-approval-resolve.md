---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# m1-55-hitl-durable-approval-resolve

#55 / #1192 production leaf: `/v1/hitl/.../answer` settles the selected
`ApprovalStore` (resolve) before `submit_hitl_answer` for
`awaiting_human_approval` pauses.

- `test_hitl_durable_approval.py` **+9**: approve/deny settle DurableApproval;
  missing/coerced `approved` refused; stale expected id; contrary first-writer;
  Binding synthetic `default`/`default` scope still answers (#2423 P1);
  elapsed deadline refuses before ApprovalStore.resolve (#2423 P2);
  ordinary human pause unchanged.
