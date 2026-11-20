---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# m1-55-hitl-durable-approval-resolve

#55 / #1192 production leaf: `/v1/hitl/.../answer` settles the selected
`ApprovalStore` (resolve) before `submit_hitl_answer` for
`awaiting_human_approval` pauses.

- `test_hitl_durable_approval.py` **+7**: approve/deny settle DurableApproval;
  missing/coerced `approved` refused; stale expected id; contrary first-writer;
  ordinary human pause unchanged.
