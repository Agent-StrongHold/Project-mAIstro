---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 32: coverage-failure revalidation

The supplied prior failure log was a stale unresolved-merge-marker syntax error
in the three canonical Run-store modules. At the assigned `3e479f39` head,
`uv run ruff check .` and `uv run ruff format --check .` both pass; no source
change was needed or made for that historical failure.

The publish-set coverage producer was re-run locally with the exact five
package suites and 87% floor. It passed at 92%. The non-publish
`maistro-server` and Hive producers were then appended to the same coverage
database and `scripts/check-diff-coverage.py` passed against the assigned
`352aea3f` base: all twelve measured changed production files met the 90% line
and 80% branch-arc floors. The archive artifact producer and the full
PostgreSQL artifact-combine workflow were not reproduced locally.

The focused real-PostgreSQL durable-idempotency producer also passed 28 tests
with `MAISTRO_REQUIRE_PG_LEGS=1` against the existing
`auto41-coverage-pg` service. This does not close #1845: task admission still
mints the Run and subsequently writes the idempotency completion separately
(`TaskQueue._admit_claimed`), so the required joint PostgreSQL Run/binding
commit, process-kill, and independent multi-replica proof remain unimplemented.
No test identities were added or removed.
