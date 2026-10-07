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

Remaining acceptance limits: no live PostgreSQL 17/18, no shipped Hive/server
process restart validation, no central migration reservation, and no trusted
GoalStatus grant. Shared-Container tests are not proof of both deployed apps.
