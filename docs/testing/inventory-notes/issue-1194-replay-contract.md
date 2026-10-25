---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +1
---
# issue-1194-replay-contract

Six core tests add evidence for the executable Graph replay contract:

- the non-retryable contract overrides a larger graph retry budget;
- `compliance.block` repeated execution upserts one penalty by its logical effect key;
- `dashboard.append_section` repeated execution leaves one section;
- repeated and concurrent `agent.delegate_remote` execution reuses one child Run and one in-process A2A task;
- the SQLite canonical store retains one effect claim across a store reload.

The catalog assertion also verifies replay semantics are emitted from the executable node contract. The server test proves repeated inbound A2A admission returns one canonical Run.
