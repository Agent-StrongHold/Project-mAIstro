---
inventory-delta:
  tests/: 0
  packages/maistro-core/tests: 0
---

# #1572 interrupted-merge salvage

Entry: `c52c787221ac1234fad6401e30d009559a469f2c`, with an unfinished
merge of `b0912ce590d51bcfe4944da57770575e50ae2e8a`. Preserved both unstaged
and staged patches outside the worktree before resolving six conflicts.

Both sides define revision `059`: unmerged Goals and integrated backlog.
The migration identity test failed before repair and `uv run alembic heads`
warned `Revision 059 is present more than once`. Preserve backlog `059`/`060`
and append Goals as candidate `061`; do not move shipped `056`/`057`/`058`.
Central reservation of `061` remains UNVERIFIED, not implied by local uniqueness.
Strengthened the existing identity test to assert the backlog ancestry and
filenames as well as Goals. The downgrade-refusal test checks both the actual
starting stamp and the script head, then asserts the failed downgrade leaves
that stamp untouched. No tests removed or added.

Merge resolution retains both historical inventory narratives with corrections,
retains the incoming backlog retention entry plus all three Goal entries, and
keeps both Goal and extension wheel-import surfaces. No new ledger classification
or authorization is introduced by the resolution.

Architecture: accepted ADR-081426-1f7c keeps execution mechanics on Attempt;
ADR-092326-97c4 keeps the shared database authoritative; ADR-091726-7c2a's
interview gate remains a consumer concern (#1823), not a second Goal store.
No execution, authorization, or Goal authority added by this repair.

Initial gate evidence:
- Exact CI vulture command passes (1329 findings, zero unclassified/forbidden).
  No vulture ledger amendment is warranted by the scan.
- `uv run python scripts/check-execution-lifecycles.py` fails: GoalStatus lacks
  an already-landed authorization in trusted base `df00785bb41b`. A candidate
  grant cannot repair this. No grant or scanner change made.
- PostgreSQL validation unavailable: Docker at `unix:///var/run/docker.sock`
  reports it cannot connect. Earlier PostgreSQL claims are not revalidated.

Validation after conflict/migration repair:
- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`:
  **46 passed, 16 skipped** (PostgreSQL legs unverified).
- `uv run pytest tests/migrations -x -q`: **38 passed, 125 skipped**.
  Identity and snapshot-byte checks pass; database upgrades remain unverified.
- `uv run alembic heads`: **061 (head)**, no duplicate-revision warning.
- Initial convergence invocation omitted required `--base` (exit 2); rerun
  against the frozen, resolved develop base is recorded below.

Additional gate evidence:
- `uv run python scripts/check-m1-convergence-freeze.py --base 9bd1a93eefc4e564041b3cc512f20b229cde64b9`: passed.
- `uv run pytest tests/test_check_execution_lifecycles.py -q`: **28 passed,
  1 failed**, at line 374, for the same unapproved GoalStatus identity.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed.
- Attempted `scripts/check-durable-table-retention.py`: not found; skipped.
  This is not a retention-gate pass.
- `git diff --check`: passed; no conflict markers remain in the six paths.

## Final merged-tree validation

Salvage committed as `fd3b1d08d`. `git fetch origin develop` resolved to the
same frozen base `9bd1a93eefc4e564041b3cc512f20b229cde64b9`; merging that tip
produced `c009078d386f5d9fffa583b70ff9631b5c66a0d7` without conflicts.
`quality/` against this base contains only the pre-existing three Goal
retention entries and GoalStatus classification. Vulture ledger equals base;
no rows/grants were invented to obtain a pass.

Executed again on that merged tree:
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`:
  **1813 passed, 311 skipped, 6 warnings**. Warnings are aiosqlite worker-thread
  callbacks on closed loops in adjacent Run tests; not hidden or treated as
  proof of clean teardown.
- `uv run pytest tests/migrations -x -q`: **38 passed, 125 skipped**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, **1328 findings = 1328 reviewed identities**, zero unclassified.
- `uv run python scripts/check-execution-lifecycles.py`: **FAILED** against
  trusted base `9bd1a93eefc4`, still the unapproved GoalStatus identity.
- `uv run python scripts/check-m1-convergence-freeze.py --base 9bd1a93eefc4e564041b3cc512f20b229cde64b9`: passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, **14961 collected identities**.

Acceptance map (current executed evidence, not historical claims):
- Goal/revision round-trip: memory and SQLite conformance pass; PG UNVERIFIED.
- Append-only/stale CAS/concurrent single winner: same conformance passes on
  memory/SQLite, including independent SQLite connections; PG UNVERIFIED.
- Parent/Project lineage and recorded ownership transition: same suite passes
  on memory/SQLite; PG UNVERIFIED.
- Admission binding and historical immutability: `test_run_goal_binding.py`
  passes on memory/SQLite; PG UNVERIFIED.
- Foreign/missing authorization equivalence: scoped conformance and real
  Container seam tests pass; PG UNVERIFIED.
- Production composition: real shared-Container exposure tests pass; inspected
  server `main.py:344` and Hive `adapters/maistro_core.py:194` call that factory.
  Both deployed-process compositions remain UNVERIFIED.
- Durable restart: SQLite close/reopen test passes for Goals/revisions and
  bound Run provenance; PG and deployed-process restart UNVERIFIED.
- No competing execution authority: convergence freeze passes against base.
- Migration identity: graph and original `056`/`057` byte checks pass, single
  head `061`; live snapshot upgrades, fresh/reapply/downgrade legs on PG17/18,
  older quota ancestry compatibility, central reservation UNVERIFIED.

Outcome: **BLOCKED**, not integration-ready. A separate trusted-base GoalStatus
policy authorization is required; this branch cannot authorize itself. Then
revalidate both PostgreSQL majors and deployed compositions. No remote writes.

Remaining acceptance limits: no live PostgreSQL 17/18, no shipped Hive/server
process restart validation, no central migration reservation, and no trusted
GoalStatus grant. Shared-Container tests are not proof of both deployed apps.
