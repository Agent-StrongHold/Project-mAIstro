---
inventory-delta:
  packages/maistro-core/tests: +4
---
# issue-1194-replay-contract

Four tests add evidence for the executable Graph replay contract:

- the non-retryable contract overrides a larger graph retry budget;
- `compliance.block` repeated execution upserts one penalty by its logical effect key;
- `dashboard.append_section` repeated execution leaves one section;
- repeated `agent.delegate_remote` execution reuses one child Run and one in-process A2A task.

The catalog assertion also verifies replay semantics are emitted from the executable node contract.
