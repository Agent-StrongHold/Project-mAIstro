---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue #41 merge-resolution validation

The develop-sync resolution preserves the canonical idempotency claim store on
Hive demo's `LocalTaskBackend`. The existing engine service test now makes its
queue double accept and assert that store, preventing the demo path from
silently using a fresh in-memory idempotency authority while its task Run is
canonical.

The coverage-unit producer also demonstrated a deterministic gate failure:
`test_an_unreachable_server_is_an_error_not_a_fallback` waited 61 seconds for
an environment-dependent localhost connection although its assertion concerns
the Container's `get_pool` exception boundary. The test now injects that
connection failure directly, preserving the no-fallback assertion without
requiring a network timeout that exceeds CI's 30-second per-test limit. The
exact core producer then passed (11,244 passed, 756 skipped, 1 xfailed in
214.92s). The complete local `coverage-unit` producer remains unproven because
this worker's Docker socket is unavailable and three `maistro-evolve` sandbox
tests require it; the covered core/canvas/rsi/bootstrap subset nevertheless
reported 91%, above the 87% floor.
