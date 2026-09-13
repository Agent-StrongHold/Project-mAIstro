---
inventory-delta:
  packages/maistro-turing/backend/tests: -1
---

# Issue #54 Turing execution convergence

The reachable Turing chat path now resolves a Workspace/Project-scoped canonical
`model.chat` Binding and records the provider call as a canonical Invocation
under the Run's NodeRun and Attempt. Coverage proves successful and unknown
provider outcomes retain Run/NodeRun/Attempt/Invocation correlation, and that
canonical admission failures return a fixed 503 instead of replaying the user
turn outside the execution spine. The chat session requires a provider callback
and cannot dispatch through its bridge directly; the backend route supplies the
canonical provider callback.
No reactor or autonomous cognitive runtime is started by this convergence.
