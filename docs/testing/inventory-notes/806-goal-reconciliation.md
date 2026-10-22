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

Mid-round follow-up: origin/develop fast-forwarded again (5f714e1be ->
53db17850, #2167 + #2148) and was merged as 5503239b6; the only conflict
was `.gitleaksignore` (both sides appended), resolved as a union. The
squash-merge cf48bbd88 of the auto-837 lane re-introduced two
generic-api-key fingerprints whose lane-commit entries (1ac446cf,
f83de3b7) no longer match the merged copy; the merged-commit fingerprints
were added per the file's own "recorded twice because it landed twice"
convention (13e8d307/c6d2fbdba precedent). gitleaks is clean on both
5f714e1be..HEAD and 53db17850..HEAD; the ten `--all` findings belong to
other unmerged lanes' refs, none reachable from this HEAD. Suite
inventory, ruff check/format, the goals tests (154 passed / 22 skipped),
check-ratchet-provenance, check-shipped-surface-truth and
check-durable-table-inventory re-verified green at 5503239b6+.

## 2026-10-20 exact-debt-ledger repair: reviewed references, not a grant

The merge-queue run at 863ac5723 failed `exact-debt-ledger` (and therefore the
`Quality gate (Pillars 1–4, 7, 8)` aggregate) on the 13 #806 identities the
previous round banked in `quality/vulture-baseline.json`. That round's residual
was correct and unlandable: `load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base, so a topic branch
cannot authorize its own floor raise, and no grant for these identities exists
on develop at fad17a87c.

Repair, verified with CI's exact invocation
(`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`, `RATCHET_BASE_REV=origin/develop`):

- The 13 identities are not dead code: they are the control-plane public surface
  (`Container.sweep_goal_leases`/`reconcile_goals`, the store protocol's
  `cancel_goal`/`reconciliation_view` plus both durable twins,
  `WakeReason.SAFETY_SWEEP`, and `ReconciliationOutcome`'s
  `skipped_asleep`/`slept_as` sweep evidence), exercised by the 105 tests in
  this note rather than by package-local src call sites. They are therefore
  named in `packages/maistro-core/src/_vulture_whitelist.py` — the file's
  documented mechanism for reviewed public/framework surface — with an inline
  #806 rationale, exactly like the existing `CampaignSelector`,
  `WorkingMemoryStats`, `RubricStore` and eval-score blocks.
- Because the whitelist references make the names used, the candidate ledger
  must shrink: `quality/vulture-baseline.json` drops those 13 banked rows
  (whole-file `--update`, reviewed as a 13-deletion diff; no other row moved).
  The scan now reports 1320 findings against the base ledger's 1321 reviewed
  identities — the difference is develop's already-pruned
  `graph/harness.py::dispatched_at` row.
- No `quality/ratchet-authorizations.json` entry was added: an unused grant in
  the branch would be a self-grant the gate cannot read, and the whitelist
  removes the finding rather than tolerating it.

The develop sync the previous round left in the worktree is committed as
b92a0a4e3 (`Merge commit 'fad17a87c…' into auto-806`, parents 863ac5723 and
fad17a87c); the tree is 0 commits behind `origin/develop` and the merge is
clean.

Re-verified at the repaired HEAD: `check-vulture-baseline` exit 0 (candidate and
trusted phases), `check-ratchet-provenance` OK (no candidate-approved
expansion), `check-shipped-surface-truth` complete, `check-reachability` exit 0
(1421 modules / 168 unreachable), `check-durable-table-inventory` 116 tables,
`check-execution-lifecycles` 19 classified, `check-wiring-reads`,
`check-owned-store-access`, `check-cross-package-imports`,
`check-promotion-surface`, `check-suite-inventory` (16810 node IDs in
`packages/maistro-core/tests`, unchanged), repo-wide ruff check/format, mypy on
the touched whitelist module, and the goals suite (105 passed).

Residual, unchanged and documented above: the mechanics ship ahead of their
production composition. `EventWakeBridge` is a tested, banked entry point but
no shipped consumer subscribes it to the canonical Event plane yet, and the
control-plane `goals` row is still separate from #1572's `canonical_goals`;
both are #805/#804 activation work, not part of this mechanics issue.

## 2026-10-20 acceptance-state repair: bank the coverage floor this branch raised

The merge-queue re-evaluation at 0fbd58674 left one aggregate-blocking
failure the vulture repair above did not touch: `quality-acceptance`
(`scripts/check-ac-state.py --run-tests --ratchet --mandate <base>`, base
fad17a87c) fails with *unbanked improvement* — this branch's 105 new tests
moved existing decided criteria to the `reachable` rung, raising
`design_coverage` from the folded floor's 39.641 to a measured 44.2377. The
ratchet's own remedy is `--bank`, which writes a per-branch note
(`quality/ac-state-notes/auto-806.json`) rather than touching any grant or
ledger, per #585's no-shared-line design; banked with exactly that command
against the real Postgres server and re-verified: the ratchet, the criteria
mandate (`criteria added or newly claimed: 0`, `unproven and not declared
so: 0`) and the chain mandate (`specs_implementing_nothing: 0`,
`adrs_without_implementing_spec: 0`, `specs_declaring_no_criteria: 0`)
all pass at HEAD.

Same round, full aggregate re-verification of every `quality.yml` sub-check
named by the Pillars 1–4/7/8 gate, each with CI's exact arguments:
ruff check/format, check-radon-baseline (134 == base) plus `radon cc
packages/*/src -i third_party --min B --total-average` (average A), xenon
(134 block violations == baseline 134, 0 module, 0 average), vulture
(candidate+trusted, 1320 findings vs base 1321), interrogate (all four
maistro-core floors pass), mypy --strict (800 files, clean under `uv sync
--locked --all-extras`), pyright (16 errors <= baseline 21), check-doc-links
(2464 files, 0 broken), check_enumerations, check-workspace-retirement,
check-route-permissions, check-principal-identity, check-frontend-typed-client,
vendor_ifeval/vendor_bfcl --check, check-reachability, the proof-envelope and
model-proof synthetic conformance steps (both fail closed),
check-credential-authority, check-wiring-reads, check-agent-store-writes,
check-contract-markers, check-convergence-matrix, check-reachability-dispositions,
check-security-inventory, check-image-inventory, check-image-pins,
check-workflow-inventory, check-backlog-consistency, check-execution-lifecycles,
check-model-egress, check-foreign-harness-egress, `pytest
packages/maistro-core/tests/fitness -v --timeout=30` (27 passed),
`pytest formal/ --timeout=120 -q` (666 passed, 1 skipped, after CI's `uv pip
install -e packages/maistro-evolve`), and the exact-debt-ledger trio
(check-ratchet-provenance, check-shipped-surface-truth, check-vulture-baseline)
plus check-durable-table-inventory (116 tables) and
check-workflow-write-safety. The goals suite passes 176/176 against the real
pgvector/pg18 server with `MAISTRO_TEST_DATABASE_URL` set, including the
PostgreSQL catalogue-agreement tests the CI postgres service runs.

## 2026-10-22 verification round: exact-debt-ledger green at the union head; queue integration simulated (no test change; delta unchanged: +105)

Re-verification at the current head 2ac6ac05a, after the two merges that
closed the recorded 863ac572 merge-queue failures: f23a0d7eb absorbed
develop's 9ef97945e and 2ac6ac05a unioned this lane's `_vulture_whitelist.py`
#806 block with the #2235 `SKILL_SECURITY_SCAN_VERSION` block, so the
whitelist carries both lanes' reviewed surface without either side's rows
being dropped.

- The exact-debt-ledger job, run locally with CI's exact arguments at HEAD:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1319 findings vs
  1320 reviewed identities, unclassified 0, never_allowlist 0),
  `check-ratchet-provenance.py` exit 0 (all seven ratchets, no
  candidate-approved expansion; `RATCHET_BASE_REV=origin/develop`),
  `check-shipped-surface-truth.py` exit 0 (matrix complete).
- Goals mechanics suite at HEAD: `pytest packages/maistro-core/tests/goals`
  158 passed / 24 skipped (all skips Postgres-DSN-gated, per the documented
  SQLite-is-the-durable-backend disposition). `ruff check .`,
  `ruff format --check .` and `check-suite-inventory --suite
  packages/maistro-core/tests` green (driver logs, re-run independently).
- origin/develop advanced one commit past the merge base (c29e0ea70, #2184,
  durable Event handler replay). Verified for the pending merge-queue
  integration without mutating this branch: `git merge-tree --write-tree`
  exits 0 (conflict-free); the synthetic merge prunes exactly the five
  `credentials` `last_error_code` ledger rows develop dropped, consistently
  with the new `events/invocations.py` consumers that make those names used.
  A throwaway `commit-tree` of the merged tree, checked out detached, passes
  the same trio — vulture exit 0 (1314 findings vs 1315 reviewed identities,
  0 unclassified, 0 never-allowlist, base c29e0ea70), provenance exit 0,
  shipped-surface exit 0 — and the goals suite (158 passed / 24 skipped).
  The actual merge is left to the merge queue per the GH006 block ("reconsider
  when the queue head clears"); the ledger/candidate consistency that failed
  at 863ac572 provably survives it on both sides of the integration.
- Residual unchanged from the 2026-10-20 round: the mechanics ship ahead of
  their production composition (`EventWakeBridge` banked but not yet
  subscribed by a shipped consumer; control-plane `goals` row separate from
  #1572's `canonical_goals`) — #805/#804 activation work. The crash-matrix
  #1823 sub-item (intake-created Goal discovered after restart) stays bounded
  by this branch's durable-facts recovery proof
  (`test_recover_enumerates_from_durable_facts_only` + `record_wake`
  marks-due); #1823's intake commit path is a separate lane and is not in
  this tree.
