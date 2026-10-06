---
inventory-delta:
  packages/maistro-canvas/tests: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
  tests/: +0
---

# Issue #41 CI-repair round 38: complete coverage-gate replay

The reported `Coverage gate (publish-set floor + diff coverage)` was replayed
from its real producers on the current candidate, rather than inferred from
prior notes. The PostgreSQL producer used the dedicated
`auto41-coverage-pg` PostgreSQL 17 service on port 55432 with
`MAISTRO_REQUIRE_PG_LEGS=1`: its migration sequence (107 passed), head upgrade,
durable core suites (5,193 passed, 92 skipped), and Canvas suite (516 passed, 3
skipped) all completed under branch coverage.

The no-service publish-set producer also completed: core 12,447 passed/890
skipped/1 xfailed, Canvas 464 passed/75 skipped, Evolve 987 passed/6 skipped,
RSI 998 passed, and Bootstrap 237 passed/1 skipped. Its publish-set coverage
report passed the workflow's 87% floor at 94%.

The gate's remaining coverage inputs then completed under `coverage --append`:
server 500 passed/8 skipped, Turing 210 passed, Turing backend 90 passed,
Design 540 passed/1 skipped, Registry plus citation check 257 passed,
Hive Conductor 3,351 passed/6 skipped, and root checks 4,485 passed/94 skipped.
`coverage.xml` passed `scripts/check-diff-coverage.py` against the assigned
base `1885c8eda09f16fc220d7fbc6e9cdb45a113ee8f`: all 13 measured changed files
met the 90% line and 80% branch thresholds. The existing forced-restart E2E
also now supplies its explicit empty child API key list, so a local legacy
`.env` key cannot stop the auth-disabled product-path proof (or unexpectedly
require credentials) before task admission; its test identity is unchanged
(+0).
