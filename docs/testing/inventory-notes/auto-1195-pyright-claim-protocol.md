---
inventory-delta:
  packages/maistro-core/tests: +0
---

# #1195 claim protocol type repair

`EffectClaimStore` is now runtime-checkable and `_admit_effect` narrows the
configured Invocation store through that protocol before awaiting `claim`.
This preserves the existing durable claim path while removing the untyped
`getattr` result that Pyright reported as a newly introduced awaitable error.
No test identifiers changed: the existing SQLite cross-connection admission
test exercises the protocol-backed `claim` path, and the PM polling suite
exercises its governed retry boundary.

Validation at this repair head: the targeted capability suites passed (11
cases), and Pyright 1.1.414 in the CI-equivalent all-extras environment
reported 21 errors, equal to the workflow baseline of 21.
