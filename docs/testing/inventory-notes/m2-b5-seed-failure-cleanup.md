---
inventory-delta:
  packages/maistro-bootstrap/tests: +7
---
# M2-B5 seed failure cleanup coverage

The Builder Docker conformance coverage gate identified unmeasured cleanup paths in
`ContainerBuilderSandbox`: a failed `__enter__` after container creation, a failed
host archive, and failures in each of the two independent container extraction
steps. Four tests prove every failure removes the ephemeral container rather than
leaving seeded candidate work alive for a later caller; the fifth proves a fully
successful pair of extracts proceeds to initialize the sanitized baseline. The
sixth covers linked-worktree Git marker parsing so a malformed marker is refused
and a valid relative marker resolves its index without evaluating host Git config.
The seventh ensures a replaced harness is refused: agent-process reaping must
never preserve an arbitrary PID-1 child as though it were the startup harness.
