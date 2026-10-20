---
inventory-delta:
  packages/maistro-core/tests: +0
---

# issue-41-verify-62003cc9

Independent verification round at the reconciled head 62003cc9f (merge of
the durable-row replay fix 45a399ea5 with the remote gitleaks allowlist
36f91dfbf; the two diverged at d93d1de74 because the fix could not push —
GH006, PR #1325 entered the merge queue). No new tests; this note records
executed evidence and one concrete repair.

## The one actionable CI failure found, and its repair

The lane brief named "Coverage gate (publish-set floor + diff coverage)" as
the failing gate. At the remote branch head that gate is green — quality run
36373720707 (36f91dfbf) shows `Coverage gate (publish-set floor + diff
coverage): success` and merge-queue quality runs for pr-1325 succeed. The
step that actually failed in that run is `ruff format check`: the pushed
gitleaks allowlist comment left `test_idempotency.py` over the line-length
limit. This round reproduces that failure locally after the merge (1 file
would be reformatted) and repairs it by restructuring the fixture so both
gates hold — `idempotency_key="shared",  # gitleaks:allow` keeps the allow
comment on the same line as the matched value (gitleaks semantics) while
ruff format accepts the block. Proven locally: `gitleaks git` over
b43175c1d..HEAD reports "no leaks found" (rc 0), `ruff format --check .` is
clean.

## Coverage gate reproduced locally at this head

Faithful local reproduction of quality.yml's producers (pgvector service,
`MAISTRO_REQUIRE_PG_LEGS=1`, DSN on the lane's auto-41-pg-cov container):

- producers: core (10769 passed / 732 skipped), canvas (399+450), evolve
  (645), rsi (786), bootstrap (232 passed; 1 bwrap sandbox failure —
  environmental, the sandbox needs CI's bubblewrap + userns sysctl),
  tests/migrations (101), PG schema suites (4369 passed), server (420),
  hive-conductor (2937);
- publish-set floor: `coverage report --fail-under=87` → 92% over 108,060
  statements (conservatively *including* server/hive data CI's floor
  excludes and *missing* the MinIO producer CI includes);
- diff gate: `scripts/check-diff-coverage.py coverage.xml --base
  b43175c1d` → ok: 12 measured changed files ≥ 90% lines / ≥ 80% arcs
  (14 changed files exempt by declaration).

## Acceptance spot-checks at this head

- `test_replay_receipt_durable_row.py` (the prior finding's repro set):
  53 passed with test_idempotency_durable + purge_driven under PG legs;
- `test_tasks_idempotency.py` + server `test_tasks_idempotency.py` +
  `test_parked_run_resume.py` + `test_spine_conformance.py`: 490 passed
  (one order-dependent flake on first combination, green on identical
  re-run and in isolation);
- hive workspace-scoped submission + username registry: green;
- vulture per-identity ledger: 1402 identities → 1402 findings, clean;
- suite inventory gates (core / server / hive-conductor): ok;
- ruff check and format: clean at the reconciled head.

## Residual, integration-side

The branch cannot be updated on the remote while PR #1325 sits in the merge
queue (GH006). The reconciled head 62003cc9f supersedes the remote tip:
integration should dequeue or merge-queue-refresh from this history so the
durable-row fix (absent from the remote tip) is not lost.
