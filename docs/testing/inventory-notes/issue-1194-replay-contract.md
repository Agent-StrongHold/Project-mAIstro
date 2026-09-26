---
inventory-delta:
  packages/maistro-core/tests: +4
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

Reconciliation correction (post-merge): of the six core tests this note
originally recorded, the `agent.delegate_remote` child-Run reuse test and the
catalog replay-semantics assertion were already shipped on develop (base
ba2f1f077 collects equivalent node IDs), so the merge retained those
develop-side copies and dropped the branch variants. The surviving measured
additions over the merge base are the four core tests above plus the server
A2A replay test.
