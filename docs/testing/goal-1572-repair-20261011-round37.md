# #1572 repair — round 37 verification and writer record (head e7e4d341b6b71)

Lane L1572, job `e33a2a80…` (e33a2a800bd646afa162342a6f9c5d8c). The previous
round ended with **no commit** (provider timeout after green driver checks);
this round re-executed the validation first-hand at
`e7e4d341b6b71b0483dd50d2203fbca8cea531db` (worktree arrived clean; nothing
below is taken from earlier rounds without being re-run) and commits this
record, resolving the no-commit block.

Driver deterministic checks at this head (job `check-*.log`): `uv sync --locked
--extra dev` exit 0; `ruff check .` and `ruff format --check .` clean; focused
pytest (goals/events/extensions/workspaces) 161 passed, 28 skipped;
`check-suite-inventory.py --suite packages/maistro-core/tests` matches baseline
(16334 identities, 0 duplicates).

## The three merge-queue reds at e7e4d341b — one root cause, read from the CI job logs themselves

The three failing job logs were fetched read-only (`gh api …/jobs/<id>/logs`)
and read in full; each contains exactly one failing assertion, and it is the
same one:

1. **test** (run 38146428836, job 114490647644): `1 failed, 4977 passed, 135
   skipped`. The failure is
   `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
   (`assert gate.main() == 0`, tests/test_check_execution_lifecycles.py:374),
   captured stdout: `baseline: base 3c761d14db94`, `19 classified lifecycles
   ->  20 discovered lifecycles`, `FAIL: the execution-lifecycle ledger does
   not match trusted policy`, sole finding `maistro.goals.model::GoalStatus:
   NEW work-state vocabulary is absent from the trusted base and has no
   already-landed authorization`. (The queue's optimistic merge candidate
   prints as `a6b2fe75cb79`; base and branch content are identical to this
   head's.)
2. **Quality gate (Pillars 1–4, 7, 8)** (run 38146428828, job 114490695995):
   every step green in the log through `pytest formal/` (ruff ×2, radon,
   version, release, doc links, enumerations, workspace-retirement,
   route-permissions, principal-identity, frontend-typed-client, vendored
   IFEval/BFCL, vulture ledger, reachability, installed-proof/selected-call
   validators, credential authority ×2, wiring-reads, agent-store-writes,
   contract-markers, convergence-matrix, reachability-dispositions,
   security/image inventories, workflow-inventory, backlog-consistency,
   alembic upgrade, ac-state mandate, mypy --strict `Success: no issues found
   in 789 source files`, pyright, formal/), then
   `uv run python scripts/check-execution-lifecycles.py` failed with the same
   sole GoalStatus finding. model-egress, foreign-harness-egress, fitness and
   interrogate never ran in CI.
3. **Coverage gate (publish-set floor + diff coverage)** (run 38146428828,
   job 114493390309): the publish-set floor step passed; the run died in the
   `pytest tests/` producer on the same single self-check (`1 failed, 5081
   passed`); diff-coverage never ran. ("Event loop is closed" lines in that
   log are teardown noise from the passing durable-event tests, not the
   failure; the job's exit is the pytest failure.)

Local reproduction at this head with CI's exact argv and base:

- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-execution-lifecycles.py` → **exit 1**, base `3c761d14db94`,
  19 → 20, sole finding GoalStatus.
- `RATCHET_BASE_REV=origin/develop uv run pytest
  tests/test_check_execution_lifecycles.py -q` → **1 failed, 28 passed**,
  captured stdout identical to CI.

## Why the only repair is a grant-only develop landing — proven mechanically this round

- `load_authorizations` reads `quality/ratchet-authorizations.json` **from the
  merge base** (`scripts/ratchet_provenance.py`; docstring: a new grant does
  not take effect in the change that introduces it — the two-merge rule). At
  base `3c761d14db94` the `execution-lifecycles` section carries rows for
  `services.rsi::RunStatus` and
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus` only — zero
  GoalStatus rows (`git show origin/develop:quality/ratchet-authorizations.json`).
- `_discover_at_revision` grandfathers only source that already existed at the
  base; `packages/maistro-core/src/maistro/goals/model.py` does not exist at
  `3c761d14db94`, so GoalStatus cannot grandfather.
- **Sufficiency proof (new this round):** the unmodified
  `scripts/check-execution-lifecycles.py::main()` was driven with the *only*
  delta being a GoalStatus entry injected into `load_authorizations` — exactly
  what a grant-only develop landing provides at the merge base. Result:
  **exit 0** — `OK: 20 work-state vocabularies, all classified (3 CANONICAL,
  8 CONVERGE, 7 DOMAIN, 2 PROJECTION)` with the authorization line printed.
  The branch code and candidate ledger row (DOMAIN, rationale) are otherwise
  complete and correct.
- No in-branch edit can legitimately flip this gate: a self-grant on this
  branch is unread by design; deleting the classification fails the candidate
  audit; deleting the enum guts the issue's required Goal lifecycle; renaming
  enum members to dodge the work-state detector would weaken the gate. None of
  these is a repair.
- No develop-sync conflict: `git fetch origin` this round; `origin/develop` is
  still `3c761d14db944a727fa0744444bc67cfe36d49f7` and `e7e4d341b` already
  merges it (HEAD message: "Merge commit '3c761d14db94…' into auto-1572").

Grant text for the owner to land on develop (grant-only change, then merge
develop into this branch and re-run the queue), under `execution-lifecycles`
in `quality/ratchet-authorizations.json`:

```json
"maistro.goals.model::GoalStatus": {
  "owner": "@BlakeMatthews-dev",
  "issue": "#1572",
  "reason": "Authorizes the DOMAIN classification of maistro.goals.model::GoalStatus introduced by the #1572 canonical Goal store. GoalStatus is the Goal's desired-state lifecycle (ACTIVE, then terminal SATISFIED/CANCELLED/FAILED/SUPERSEDED); Runs execute work toward a Goal and keep the canonical RunStatus, and a Goal never drives a scheduler, admits work, or mirrors Run/NodeRun/Attempt — a genuinely different lifecycle, not a second execution identity. The #1572 branch classifies it in quality/execution-lifecycles.json; this grant must exist at the base before that classification can pass check-execution-lifecycles.py."
}
```

**Vulture lane, as ordered by the repair brief:** `uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → `1323 reviewed identities -> 1323 findings`, unclassified
0, never_allowlist 0, **exit 0**. No `quality/vulture-baseline.json` amendment
applies.

## Acceptance criteria re-executed first-hand at e7e4d341b

Fresh round-37 databases `r37g18` (pg18.6, `auto-1572-pg` 127.0.0.1:55712) and
`r37g17` (pg17.11, `auto-1572-pg17` 127.0.0.1:55717), each created empty and
migrated empty → head **063** with `DATABASE_URL=… uv run alembic upgrade head`
(exit 0 both majors; final `alembic_version` = 063; `canonical_goals`,
`canonical_goal_revisions`, `canonical_goal_transitions` catalog-verified on
both majors).

| Criterion | Executed evidence this round |
|---|---|
| Goal/GoalRevision round-trip on all three backends via shared conformance suite | `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=… uv run pytest packages/maistro-core/tests/goals -q` → **70 passed, 0 skipped on pg18** and **70 passed, 0 skipped on pg17** (memory + SQLite + PostgreSQL through one parametrized suite; legs enforced, so no silent skip) |
| Revisions append-only; stale-revision refused; concurrent update has one winner | inside the 70 (`test_goal_store_conformance.py` legs, all three backends) |
| Subgoal lineage preserves parent/Project; recorded ownership transition | inside the 70 |
| Run admission binds goal_id/goal_revision; binding immutable; Run outcome never moves Goal state | inside the 70 (`test_run_goal_binding.py` legs) |
| Foreign Goal indistinguishable from missing across Workspaces | inside the 70 (canonical `maistro.workspaces.authorization` seam) |
| Production composition wires the store; shipped Container proof | inside the 70 (`test_goal_wiring.py`, incl. shipped-Container exposure, sqlite/pg/memory selection, bare-DB schema bring-up) |
| Installed-base forward upgrades from real develop snapshots, no stamp edit | `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest tests/migrations -q` → **168 passed on pg18 (3m21s)** and **168 passed on pg17 (3m22s)**, including the `c560d4c` and `4675101` installed-base upgrades |
| Fresh-install single-head/unique identity + downgrade/refusal coverage | inside the 168 (`tests/migrations/test_migration_chain.py` et al.) |
| Restart readback of a supported durable composition | `test_goal_restart_readback.py` inside the enforced-leg 70 |
| No second executor / product-private Goal lifecycle | `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67cfe36d49f7` → exit 0 ("no unapproved new architecture island") |
| Acceptance-state ratchet + mandate at the merge base | fresh `r37ac` on pg18; `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 3c761d14db944a727fa0744444bc67cfe36d49f7` with both PG vars → **exit 0**, chain mandate 0/0/0 |
| mypy --strict (Pillar 4, CI argv) | `MYPYPATH=<all package src> uv run mypy --strict packages/maistro-core/src` → `Success: no issues found in 789 source files` (this venv lacks `--all-extras`; without MYPYPATH the only errors are 5 `maistro_bootstrap` import-not-found artifacts of the venv, not of the tree — CI green) |
| Quality-gate steps CI never reached | model-egress exit 0 (20 callers, no candidate-approved expansion); foreign-harness-egress exit 0; credential-authority exit 0; fitness `23 passed`; reachability exit 0; interrogate steps executed locally at their CI floors, all green |

## Inventory

No test file added, removed, or changed this round → no suite-inventory delta
and no `docs/testing/inventory-notes/` entry required (`git status` shows only
this document; the driver's `check-suite-inventory.py` run already matched the
recorded baseline).

## Disposition

All acceptance criteria are executed and green on both supported PostgreSQL
majors at `e7e4d341b`; the three red merge-queue checks share one external root
cause, and this round adds a mechanical sufficiency proof that landing the
GoalStatus authorization grant on develop — then merging develop into this
branch — flips the gate to exit 0 with no other change. That landing is a
GitHub mutation outside this lane's authority. No code, tests, or ledger edits
this round; this file is the round record, and the residual risk is exactly
one: the grant-only develop landing has not happened yet.
