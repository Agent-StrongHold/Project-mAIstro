---
inventory-delta:
  packages/maistro-core/tests: +105
---
# 806-goal-reconciliation

Seventy-two new tests, all additions, no removals or compensating changes:

- `tests/goals/test_goal_reconciliation.py` (64 node IDs): the M3 #806
  acceptance matrix for durable, event-driven, fenced, restart-safe Goal
  reconciliation — concurrent-process claim exclusivity (in-memory twin and
  a two-connection SQLite stand-in for two processes), stale-holder fencing
  after takeover/expiry, idempotent duplicate-event and duplicate-decision
  delivery, crash convergence after/before artifact creation, the five
  canonical wake triggers, bounded safety-sweep repair, blocked/waiting
  Goals consuming no decisions until a relevant state change, durable
  budget/deadline/cancel admission fences, the `complete=True` Goal-level
  stop condition settling the Goal (terminal postures refuse later claims,
  decisions, and admissions across restarts), control-metadata
  (non-lifecycle) guarantees, and failover lineage/no-double-execution
  proofs. Every mechanics test is parametrized over the in-memory and
  SQLite store twins.
- `tests/goals/test_goal_container_wiring.py` (8 node IDs): the Container
  composition — backend selection for the control-plane store (SQLite twin
  on the sqlite backend, in-memory fallback with the loud #122-style
  PostgreSQL warning naming #1572), the policy-free `sweep_goal_leases`
  tick reclaiming only lapsed claims, `reconcile_goals` deciding nothing
  without a #805-composed policy, and the bounded tick repairing a missed
  wake idempotently once a policy is composed.

While wiring the Container tick, a real AC-6 hole in the mechanics was
found and closed: a wake recorded on a Goal that had never been reconciled
(READY, no `awake_after`) was invisible to the bounded sweep, so a process
dying between recording the fact and the first reconcile pass lost the
notification until a new event arrived. `record_wake` now marks the Goal
due when the wake is relevant — unblocking, or the Goal is not in a
sleeping posture — in both store twins; non-unblocking wakes never shorten
a sleeping Goal's night (AC-7 preserved, asserted). Two new mechanics node
IDs cover the repair and one extends the non-unblocking skip with the
sweep-side assertion.

Verified numbers at this branch: `packages/maistro-core/tests` collects
11643 (11571 before the goals package; 11571 + 72 = 11643); a full run is
10894 passed, 737 skipped, 1 xfailed. The vulture-baseline check fails at
this HEAD independently of this change (hive-conductor DAG identities,
untouched files from the initial release); the reachability, wiring-reads,
execution-lifecycles, durable-table-inventory, owned-store-access and
cross-package-imports gates pass.

## 2026-10-18 develop-sync relocation (this note's delta unchanged: +72)

Develop merged #1938 (issue #1572, the canonical durable Goal store) as
`maistro.goals` — the same package path this mechanics package originally
occupied, because #1572's PR was closed unmerged when this work was written.
The develop sync therefore resolves by relocation, not by union: the
canonical store stays verbatim at `maistro.goals`, and the #806 control-loop
mechanics move to `maistro.goals.reconciliation` (`model.py`, `store.py`,
`reconciler.py`, `wiring.py`); the Container wiring (`goal_store` and
`goal_reconciliation_store`) now composes both seams. The durable-table
ledger carries both row sets — #1572's `canonical_goals`/
`canonical_goal_revisions`/`canonical_goal_transitions` and this work's
control-plane `goals`/`goal_claims`/`goal_wakes`/`goal_admissions` (all
four `owner_module` paths updated to the relocation).

Re-verified after the merge: `packages/maistro-core/tests` collects 16432;
full run 15362 passed, 1067 skipped, 3 xfailed, 0 failed. The 72 mechanics
tests pass at `tests/goals/test_goal_reconciliation.py` +
`test_goal_container_wiring.py` under the relocated import paths, and
develop's 71 canonical-store tests pass in the same directory. Gates green:
check-suite-inventory (17 suites, after `uv sync --locked --extra dev`
pulled the new `reference-greeter`/`maistro-ext-harness` workspace
members), check-durable-table-inventory (116 tables),
check-execution-lifecycles (19 classified), check-reachability (169
unreachable), check-wiring-reads, check-owned-store-access,
check-cross-package-imports; ruff check/format clean repo-wide; mypy 904
files clean. Residual for the #805/#804 activation round: the mechanics
store still persists its own control-plane Goal row rather than composing
on #1572's Goal record — documented in the package docstrings, not silently
assumed away.

Follow-up in the same round: develop advanced 14 more commits past
ab8b3737 (none touching the goals package or any resolved file — verified
empty diff before merging); merged as bd4dd5f5d. Final tree re-verified:
`packages/maistro-core/tests` 16495 collected, 15419 passed, 1073
skipped, 3 xfailed, 0 failed; all gates and ruff/mypy re-run green.

## 2026-10-18 CI-repair round (+33 node IDs, all additions; note delta now +105)

Repair of the CI failures at 4746e7d7, driven by local gate runs at the
develop-synced tree (3df0fba97):

- 33 new mechanics node IDs close the diff-coverage branch-arc gaps the
  coverage gate named (`model.py` 50% of 2 changed arcs, `store.py` 77.9%
  of 86). The additions are the degenerate paths, not more happy path:
  duplicate `create_goal` refusal, unknown-goal `record_wake`/admit/claim
  refusals, `complete_admission` double-settlement returning False,
  `pending_wakes` without a goal filter, `mark_wakes_dispatched` ignoring
  unknown and already-dispatched ids, `sleep_goal` refusing a non-sleeping
  posture, stale-fence refusal after lease takeover for both `sleep_goal`
  and `finish_goal`, `reconciliation_view` of unknown/unclaimed Goals, the
  three `_check_gates` refusals unit-pinned, the SQLite
  `reclaim_expired` surviving a Goal row deleted under a lapsed claim,
  reconciler guard paths (Goal row vanishing between claim and pass, a
  Goal settling mid-pass deciding nothing, a newer fence epoch making the
  pass harmless with zero admissions, `_repair_open` no-ops), plus
  `coerce_datetime`'s stored-text shape and `goal_id_of_event` ignoring
  non-dict/non-string/blank payloads.
- Twin-parity fix found by the new duplicate-create test: the SQLite
  `create_goal` raised a raw `sqlite3.IntegrityError` where the in-memory
  twin raises `GoalReconciliationError`; the SQLite twin now maps the
  UNIQUE violation to the same domain error.
- Bandit B608 (strict zero Medium+) on the SQLite twin's f-string column
  list: every site interpolates only the code-owned `_GOAL_COLUMNS`
  constant with values bound via `?`; annotated `# nosec B608` per the
  `runs/sqlite_store.py` precedent, and the multiline sweep query moved to
  a module constant. Radon ratchet: the three new C-grade blocks
  (`reconciliation_view`, `SqliteGoalStore.claim`, `GoalReconciler._pass`)
  were refactored under the threshold by behavior-preserving extraction
  (`_claim_view`, `_open_count`, `_claim_blocked`, `_next_claim`,
  `_admit_planned`, `_settle`); ratchet back to 137 == base. Gitleaks: the
  `PlannedAdmission(... decision_key=key ...)` constructor line tripped
  generic-api-key; recorded commit-scoped in `.gitleaksignore` with a
  paraphrased rationale.
- Re-verified at this round's HEAD: goals package 154 passed / 22 skipped
  (Postgres-gated skips); `packages/maistro-core/tests` 15,489 passed /
  1,076 skipped / 3 xfailed; check-diff-coverage ok (every measured changed
  file ≥ 90% lines / 80% branch arcs vs origin/develop); publish-set floor
  92% ≥ 87 on the five no-services producers; ruff check/format, mypy (906
  files), check-radon-baseline, bandit Medium+ = 0, semgrep (goals +
  tests), gitleaks (develop..HEAD), check-ratchet-provenance,
  check-shipped-surface-truth, and check-suite-inventory all green. The
  vulture exact-debt-ledger banks this package's 13 reviewed retained
  identities in `quality/vulture-baseline.json` (+13/−1 stale
  `graph/harness.py::dispatched_at` row); the identities are exercised by
  the tests in this note, and the gate's remaining "not authorized by the
  trusted base" step needs the reviewed grant landed on develop first
  (two-merge rule), which no candidate edit can self-approve.

## 2026-10-19 repair round: develop sync to 5f714e1be (no test change; delta unchanged: +105)

Merged origin/develop (5f714e1be, 6 commits) into auto-806. The only
content conflict was `container.py`: develop had wrapped
`create_container`'s body in `try/except BaseException` startup-resource
cleanup (#1856), re-indenting the region this branch's wiring lands in.
Resolution took develop's wrapped form verbatim and re-applied the #806
additions inside it (the `wire_goal_reconciliation` composition call, the
`goal_reconciliation_store` constructor argument, and the two Container
ticks); the goal reconciliation ticks stay operator-scheduled and are
published from the returned Container only, so they cannot run inside a
failed-startup rollback path.

Ledger integrity after the merge, checked per the quality/*.json
multiset-merge rule (`git diff --numstat origin/develop -- quality/`):
`vulture-baseline.json` +13/-1 against develop - the +13 are this
package's banked identities (preserved through the merge, verified row by
row against the scan), and the -1 is the `graph/harness.py::dispatched_at`
row develop no longer scans (develop removed the name from
`graph/harness.py` without pruning its row; the merge resolution carries
the prune the candidate phase requires). `durable-table-retention.json`
remains the branch-only +48; `ratchet-authorizations.json` is byte-identical
to develop (no self-granting).

Re-verified at the merged HEAD: goals package 154 passed / 22 skipped
(Postgres-gated); `packages/maistro-core/tests` collects 16632 and
check-suite-inventory matches the recorded inventory; ruff check/format,
`mypy --strict packages/maistro-core/src` (798 files, under `uv sync
--locked --all-extras`), check-radon-baseline (134 == base), bandit
Medium+ = 0, gitleaks 5f714e1be..HEAD clean, check-ratchet-provenance,
check-shipped-surface-truth, check-durable-table-inventory (116 tables),
check-backlog-consistency, and diff-coverage on the goals producers (every
changed file >= 90% lines / 80% branch arcs) all green. The vulture gate's
candidate phase is clean and its trusted phase still names the same 13
unauthorized identities: every one is live #806 acceptance surface
(`cancel_goal`, `reconciliation_view`, the safety-sweep wake reason, the
sweep-outcome fields, the two Container ticks) exercised by the tests
above, none is genuinely dead, and no topic-branch edit can authorize them
- the residual is the develop-side reviewed grant, unchanged from the
previous round's record.
