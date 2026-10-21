---
inventory-delta:
  packages/maistro-core/tests: 42
---

# Issue 76 evidence-driven backend repair

Eight Kata cases (two directory-swap transfers, two real-child stream overflows,
cancellation/reap, timeout/reap, retryable teardown, and surfaced removal failure), two canonical adapter wiring checks, and one launcher
resource-ceiling check; 21 in-memory convergence mutations covering direct,
aliased, and qualified constructors; 10 live selected-Kata deployment checks.
The latter explicitly skip without Kata/KVM and cannot establish containment
on an unsupported host. Other tests exercise actual backend methods and
selector configuration; they do not claim live VM containment. Regression runs before
implementation are recorded in docs/implementation-76-repair.md.
