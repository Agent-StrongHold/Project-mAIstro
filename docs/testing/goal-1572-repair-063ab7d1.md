# Issue #1572 repair evidence — head `063ab7d1dad3`

Lane L1572 repair round, worktree `/home/dev/Git/wt/auto-1572`, branch `auto-1572`.
Dispatched head `063ab7d1dad34d22e2c75e3351c497f81e804740`, develop base
`d592654aca614fb74467487542693c46b3aa30fb`. Worktree started clean; this round
changed only this document. No test, source, ledger, grant, or workflow edit was
made, so no inventory delta applies.

## Sole red gate: execution-lifecycles (external prerequisite, re-proven first-hand)

```text
uv run python scripts/check-execution-lifecycles.py
  ratchet: execution-lifecycles  [python ast, metric v3]
  baseline: base d592654aca61 / candidate: 063ab7d1dad3
  19 classified lifecycles -> 20 discovered lifecycles
  FAIL: maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent
        from the trusted base and has no already-landed authorization   (exit 1)

uv run pytest tests/test_check_execution_lifecycles.py -q
  1 failed (test_the_shipped_ledger_matches_the_shipped_code), 28 passed
```

The candidate ledger entry (`quality/execution-lifecycles.json`, DOMAIN,
landed in `71702e2ae`) cannot self-authorize:
`scripts/ratchet_provenance.py` loads authorizations from the **merge base**
(`d592654aca61`), whose `quality/ratchet-authorizations.json` carries no
`maistro.goals.model::GoalStatus` grant, and `origin/develop` is still at
`d592654aca61` (verified this round) — so no sync can supply it.
[ADR-032 §7](../../docs/adr/ADR-032-contracts-as-acceptance-criteria.md):
"A candidate-only identity still needs an already-landed grant; adding a
candidate ledger entry cannot authorize it."

In-lane alternatives were evaluated and rejected on the evidence:

- **Land the grant here** — prohibited: ratchet grants are two-merge artifacts
  and this lane may not mutate `quality/ratchet-authorizations.json` or GitHub.
- **Reuse the canonical `RunStatus`** ("pure imported-type reuse does not
  create another lifecycle", ADR-032 §7) — architecturally wrong: the issue
  mandates "A Run's outcome never sets Goal state implicitly", and
  SATISFIED/SUPERSEDED have no RunStatus counterpart.
- **Rename the vocabulary off the work-state word list** — detector evasion,
  the exact move ADR-032's opening paragraph forbids ("must not make a
  competing execution owner invisible"); already rejected in
  `docs/1572-repair-checkpoint.md`.

This matches the prior verifier's finding: the repair is out-of-branch — an
owner lands the `GoalStatus` authorization on develop, then this branch syncs.

## Everything locally executable is green at `063ab7d1dad3`

| Gate (CI-exact form) | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (3246 files) |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -q` | 55 passed, 16 skipped |
| `uv run pytest packages/maistro-core/tests/runs -q` | 1218 passed, 280 skipped |
| `uv run pytest packages/maistro-core/tests/events -q` | 331 passed, 51 skipped (PostgreSQL legs skip: no server here) |
| `uv run pytest packages/maistro-core/tests/security/test_strike_tracker_conformance.py -q` | 21 passed, 19 skipped (same) |
| `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py tests/migrations/test_run_store_planner_stability.py tests/migrations/test_task_admission_generation_upgrade.py tests/migrations/test_capability_invocation_effect_index_migration.py -q` | 9 passed, 52 skipped (live DB legs need PostgreSQL) |
| `python scripts/verify-wheel-imports.py --dist <built 12 wheels> --python 3.12` | PASS — all wheels import clean, including the branch's `maistro.goals` public-surface entry and sibling-constraint hardening |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS — 1323 reviewed identities = 1323 findings; no amendment warranted |
| `uv run python scripts/check-model-egress.py` | PASS |
| `uv run python scripts/check-foreign-harness-egress.py` | PASS |
| `uv run python scripts/check-convergence-matrix.py` | PASS (52 subsystems / 1384 modules) |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `uv run python scripts/check-m1-convergence-freeze.py --base d592654aca614fb74467487542693c46b3aa30fb` | PASS — no unapproved new architecture island |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS (driver check-4, this tree) |
| integration-scope required-set resolution (`ci_merge_group_scope.py` + `check-integration-scope.py`) | resolves: docker-build, durable-events, hive-conductor-e2e(+ui), object storage, postgres pg17/pg18, strike-ladder, wheel-imports |

## Environmentally unverifiable this round (unchanged from prior rounds)

- Docker daemon unavailable at `unix:///var/run/docker.sock`: `docker-build`,
  live `postgres (pg17/pg18)` legs, `durable-events`/`strike-ladder`
  PostgreSQL legs, `hive-conductor-e2e(+ui)`, and MinIO object-storage leg
  could not execute locally.
- Therefore the issue's live installed-base upgrade criteria (populated
  PostgreSQL fixtures from `c560d4c`/`4675101`, forward upgrade without stamp
  reset, durable reopen on both majors) remain UNVERIFIED here, as recorded in
  `docs/1572-repair-checkpoint.md`.

## Disposition

**BLOCKED on an external prerequisite**: the `maistro.goals.model::GoalStatus`
execution-lifecycle authorization must land on develop separately (owner
action), after which this branch syncs and the gate passes with the existing
DOMAIN classification. No in-lane edit can produce that state without violating
the two-merge rule, the lane's grant prohibition, or ADR-032's
no-invisibility contract. All locally executable gates are green and recorded
above; no integration approval or issue closure is claimed or performed.

Progress: {checked: 17, done: 16, skipped: 0, errors: 1 (external lifecycle
authorization), next: owner lands the GoalStatus grant on develop; then sync
`auto-1572` and rerun `scripts/check-execution-lifecycles.py` plus the
Postgres-bearing legs on PG-infrastructure}.
