# #1572 repair — job b571

## Frozen scope and salvage

Assigned branch `auto-1572`, starting HEAD
`9e3b94c539ba9ca952f3019213e08704615bb7b1`, develop snapshot / active
MERGE_HEAD `66f3cea9e98980f146a12cf3142d66e30986d276`.
Only issue #1572 and its supplied evidence were processed. The initial tree
contained a pending develop merge; staged and unstaged diffs were preserved
outside the worktree before resolution. No fetch of a moving develop tip,
GitHub mutation, reset, restore, or cleanup was performed.

Read accepted ADR-081226-9944 (ownership), ADR-081226-a66b (execution),
ADR-087 (schema evolution), ADR-082426-2192 (server composition), and
ADR-092326-97c4 (shared PostgreSQL). This repair preserves canonical
Goal -> Graph -> Run -> NodeRun -> Attempt and the existing Workspace
authorization seam. No architectural exception or policy bypass is proposed.

## Evidenced repair

Driver `check-1.log` and `check-2.log` failed on conflict markers in
`tests/migrations/test_capability_invocation_effect_index_migration.py`.
The pending merge also combined two migrations claiming revision `061`.
The assigned develop snapshot had already landed HITL 061; the unmerged
Goal migration now follows as `062`. Landed 056, 057 and 061 retain their
content and ancestry. Existing chain tests and current migration references
were updated; historical reports remain historical.

Installed-base tests now additionally build the actual assigned HITL develop
snapshot, populate it, forward-upgrade without stamp editing, preserve the
HITL index/user-model/Run data/planner artifacts, and exercise durable
Goal/revision/bound-Run close/reopen readback. The existing readback test now
runs from both actual 056 and 057 snapshots. Inventory delta: `tests/: +2`.

## Validation recorded so far

Logs: `/home/dev/maistro/jobs/b571cef37c10495dab01eebd5796b7d6/repair-*.log`.

- CI-exact Vulture command: PASS; no unbanked identities, no ledger amendment
  needed. No quality ledger or grant was changed by this repair.
- `uv run python scripts/check-execution-lifecycles.py`: FAIL. Trusted base
  lacks already-landed authorization for `maistro.goals.model::GoalStatus`.
  This cannot be fixed by a candidate grant or hiding the enum from the gate.
- Offline goals + runs pytest: PASS (see log for skip/warning counts).
- `uv run alembic heads`: PASS, single `062` head.
- `uv run pytest tests/migrations -x -q`: **165 passed** on local PostgreSQL
  **18.6**, including actual 056/057/061 snapshot upgrades, fresh install,
  downgrade/refusal/reapplication, and close/reopen Goal provenance.
- `uv run pytest packages/maistro-core/tests/goals -x -q`: **69 passed** with
  PostgreSQL mandatory, covering memory, SQLite and PostgreSQL conformance.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS.
- Initial full-tree lint passed; formatting identified only the modified
  installed-base test and was applied there. Final checks follow below.
- First convergence invocation omitted required `--base` and exited 2;
  this is not a gate result. Corrected invocation follows below.

PostgreSQL validation uses the existing local PG18 cluster and newly created,
job-specific database `maistro_1572_b571`, not a prior run's database. The
Docker socket is unavailable; PG17 has not been executed in this round.
Central migration reservation and the complete older supported-history audit
remain UNVERIFIED. Both shipped process startups require separate evidence;
Container factory tests alone are not a claim to have booted Hive/server.

## Status

Repair work is not integration approval. The missing trusted-base GoalStatus
grant remains an external blocker.

## Final evidence and acceptance map

The merge/repair commit is `df65f668d570db79f9ba403bbe28d56e0b4578ae`, with
parents exactly the assigned starting HEAD and develop snapshot above.
Post-merge lifecycle validation still fails, now explicitly against trusted
base `66f3cea9e989`. `tests/test_check_execution_lifecycles.py:374` also fails
(28 other tests pass). No grant or ledger edits were used to bypass this.
Post-merge CI-exact Vulture passes: 1,326 reviewed identities, 1,326 findings.

Final commands:

| Command | Executed result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,187 files |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs -x -q` (offline) | 1,241 passed, 286 skipped, six aiosqlite worker-thread warnings from existing Run tests |
| `uv run pytest tests/migrations -x -q` (PG18) | 165 passed |
| `uv run pytest packages/maistro-core/tests/goals -x -q` (PG18 required) | 69 passed |
| `uv run pytest packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` (PG18) | 2 passed |
| `uv run python scripts/check-m1-convergence-freeze.py --base 66f3cea9e98980f146a12cf3142d66e30986d276` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 15,659 identities |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS, 5,018 identities |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS before and after merge |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL before and after merge: missing trusted-base GoalStatus grant |
| `uv run pytest tests/test_check_execution_lifecycles.py -q` | 28 passed, 1 failed at line 374 |
| `uv run alembic heads` | PASS, single 062 head |

For PG18 commands, `DATABASE_URL`, `MAISTRO_TEST_DATABASE_URL` and
`MAISTRO_TEST_PG_DSN` identify the dedicated local `maistro_1572_b571`
database; `MAISTRO_REQUIRE_PG_LEGS=1` is set for Goal conformance and migration
validation. No skipped PostgreSQL leg is counted as passed.

**Regression sensitivity:** the strengthened static identity test rejects a
temporary migration tree restoring the original Goal 061 collision. The new
live `test_an_installed_base_at_hitl_061_forward_upgrades` was also invoked
against that colliding tree on a separate fresh PG18 database
`maistro_1572_b571_regression`: the actual develop snapshot migrated
successfully; the candidate's ordinary forward upgrade failed, and the new
test rejected it. The same test passes in the repaired 165-test migration run.
Both experiments leave the real worktree unchanged. Exact output is in
`repair-regression-proof.log` and `repair-live-regression-proof.log`.

| Acceptance criterion | Evidence / limitation |
| --- | --- |
| Goal and GoalRevision round-trip on memory, SQLite, PostgreSQL | 69-pass Goal run; shared conformance `test_goal_round_trips_through_the_backend` on all three legs |
| Append-only revisions, stale refusal, one concurrent winner; final terminal state | Shared `test_goal_revision_chain_is_append_only_with_one_cas_winner`, lifecycle and concurrent-transition tests passed on all three backends |
| Subgoal parent/Project preservation; recorded ownership transition | Shared lineage and agent-reassignment tests passed on all three backends |
| Admission binds immutable Goal/revision provenance | `test_run_goal_binding.py` passed on all three Run backends, including terminal transitions; actual 056/057/061 upgraded-store reopen readback passed. Dedicated post-admission advancement of the bound Goal revision remains UNVERIFIED |
| Workspace isolation and foreign equals missing | Shared principal isolation/refusal tests passed on all three Goal backends via `ScopedGoalStore` / canonical `WorkspaceAuthorizer` |
| Production composition exposes the store | Container exposure/end-to-end authorized seam/backend selection tests passed. Reachable source: `container.py:2362,2648`, server `main.py:344`, Hive `adapters/maistro_core.py:195`. Full deployed Hive/server process restart tests remain UNVERIFIED |
| No parallel GoalRun/executor/private lifecycle | Convergence freeze passed against assigned develop; no execution-authority changes in this repair |
| Preserve shipped 056/057 meaning/ancestry; append unused Goal ID | Static and snapshot byte-identity checks passed, now also pinning landed HITL 061; Goal 062 is the unique local head. Central reservation remains UNVERIFIED |
| Populated actual historical snapshot upgrades, no stamp rewrite | PG18 actual c560d4c/4675101/66f3cea9 snapshot forward-upgrades passed; PG17 UNVERIFIED |
| Three Goal tables usable; facts/keys/Runs/planner artifacts survive; reopen Goal/revisions/bound Run | PG18 installed-base tests passed, including durable readback from both 056 and 057 plus new 061 snapshot; PG17 UNVERIFIED |
| Fresh install, unique head, downgrade/refusal/reapplication; older shipped-history compatibility | 165 PG18 migration tests passed; complete older-history/quota-ancestry compatibility audit and PG17 remain UNVERIFIED |

`integration-scope` is an evidence aggregator, not a local functional test.
The workflow-equivalent classifier over the actual base...HEAD diff requires
all specialized legs. The named script was executed with that measured scope
and **no fabricated `--result` successes**; it correctly exits 1 for missing
exact-head Docker, durable-events, Hive E2E, MinIO, PG17/PG18, strike-ladder and
wheel-import check results (`repair-integration-scope.log`). Local PG18 tests
do not establish green GitHub producer jobs. No push or GitHub polling was done.
The supplied failure does not identify a more specific failing producer, so
its original cause remains UNRESOLVED rather than guessed.

Repair-specific files are the renamed Goal migration, conflict-resolved chain
test, installed-base tests, inventory note, this report, and current migration
references in Goal wiring/tests, schema parity, migration chain and CI comments.
The merge also preserves every incoming develop change. Existing quality-ledger
deltas versus develop (39 retention lines, four lifecycle lines) predate this
repair and were not amended. The upstream inventory note has a pre-existing
blank-line-at-EOF diff warning; it was preserved, not silently cleaned up.

**Handoff: BLOCKED.** Next: obtain an independently landed GoalStatus policy
grant, sync that exact authorized base, and rerun lifecycle/integration evidence;
execute PG17 and the remaining acceptance gaps above. One assigned item checked;
merge/migration repair committed; issue acceptance is not fully complete.
