---
inventory-delta:
  packages/maistro-core/tests: +0
---

No new tests; this round re-proved every gate the three 0b89f4c3c CI failures
ran, at the repair head 36ccb93d448f, and found no defect to repair.

# auto-72 verifier repair 3 (gate re-proof at 36ccb93d; local-artifact trap)

Verification-only round. The driver's deterministic check logs were absent
from the job directory, so every check below was executed locally against
HEAD 36ccb93d448f (merge-base with origin/develop = 8bfd35903f49).

- **Quality gate pillars, all exit 0:** ruff check, ruff format --check,
  radon ratchet (67 -> 67), xenon (67 <= 77), vulture per-identity ledger
  (1403 reviewed identities -> 1403 findings, base 8bfd359 -> candidate
  36ccb93d — balanced, so no ledger amendment was needed or made),
  reachability, credential authority, agent-store-writes, contract markers,
  convergence matrix, doc links, enumerations, bump_version, release
  consistency, IFEval/BFCL vendor provenance, durable-table inventory
  (65 tables with declared retention).
- **Wiring-reads ratchet:** 11 -> 11 unread vs RATCHET_BASE_REV=origin/develop,
  exit 0; tests/test_check_wiring_reads.py +
  packages/maistro-core/tests/test_container_wiring.py 78 passed.
- **Coverage gate, diff leg reproduced:** producers re-run (core suite
  10577 passed; test_elevation_durable.py's 6 PostgreSQL legs live against
  pgvector:pg18 with MAISTRO_REQUIRE_PG_LEGS=1; server suite 399 passed),
  combined and `scripts/check-diff-coverage.py coverage.xml --base
  8bfd35903f49` exits 0: 4 measured files at/above 90% lines / 80% branch
  arcs, 10 exempt. The publish-set 87% floor was green at 0b89f4c3c (the job
  proceeded past it into the root-suite producer where it died) and
  36ccb93d only adds lines those producers cover at >=90/80, so the
  aggregate cannot cross the floor; full multi-producer floor arithmetic was
  not re-run locally.
- **Migration chain live:** tests/migrations/test_migration_chain.py 11
  passed against an empty pgvector:pg18 (001 -> 044, incl. the 044 re-parent
  onto the 039 tip).
- **#72 contract suites:** test_sqlite_schema_concurrency.py,
  test_sqlite_usage_log.py, test_health.py, test_strike_tracker_health.py,
  test_main.py (19) all green with the live DSN.
- **Root tests/ suite:** 3818 passed + 1 failure that is NOT a branch defect:
  `test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` failed on
  `quality/ac-state.json` — an UNTRACKED, gitignored (.gitignore:74),
  regenerable cache that an earlier worker's `check-ac-state.py` run left in
  this worktree. `discover_quality_json` (scripts/check-branch-independence.py:211)
  rglobs `*.json` with no gitignore awareness, so ANY worktree where that
  script ran fails this test locally; CI's clean checkout cannot see the
  file. Proof it is not a #72 regression: the branch's only quality/ change
  is the classified `quality/durable-table-retention.json`, and
  `git diff 8bfd35903..HEAD` over check-branch-independence.py, the
  repository test, and .gitignore is empty. The cache was relocated
  byte-preserved to /tmp (ac-state-backup-*.json) and the test then passed;
  the prior worker's untracked pytest_output.log was relocated to the job
  directory as prior-worker-pytest-output.log (cmp-verified).
- **Residual, out of scope:** the gitignore-blind rglob above will keep
  tripping this test in dirty worktrees; it belongs to a CI-repair lane, not
  #72. Pre-existing develop bug documented in
  auto-72-ci-repair-wiring-diffcov.md (test_tasks.py result-body leg with a
  PG DSN exported) remains owned elsewhere.
