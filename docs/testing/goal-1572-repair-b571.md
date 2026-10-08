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
grant remains an external blocker. Final results and acceptance map follow.
