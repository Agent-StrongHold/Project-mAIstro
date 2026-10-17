# Issue #860 — repair round 2635d45c

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `ad8fbf3e3d6a8128b6f31d88a26dab70b29e5b3f`; supplied base `9bd1a93eefc4e564041b3cc512f20b229cde64b9`.
- Initial status clean; no incoming uncommitted work to salvage.
- Evidence: supplied dispatch snapshot, prior result `1f37993f`, and prior failed `98a11313/check-3.log`. Current job directory contains no check logs.
- Inspection scope: repository instructions, relevant execution/admission ADRs, existing soak runner/profile/promotion tests, production rate-limit middleware, CI vulture checker/workflow and ledger.
- Candidate edits restricted to this report, and evidence-supported fixes to those scoped files (with inventory note if tests change). No other issue/PR processing or remote mutation.
- Ambiguity: supplied base-to-head diff includes unrelated historical changes. Treat this as inherited branch state, not authorization to repair unrelated packages or synchronize develop; prior block reports missing RC evidence, not a merge conflict.

## Progress

Fresh validation: exact requested vulture scan passed (1332 findings / 1332 reviewed identities, zero unclassified/forbidden). No ledger amendment is warranted. The supplied historical check-3 failure is not reproduced: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed (37 passed, 6 skipped). Database-dependent skipped cases are not evidence of live replica safety. Current load profile explicitly identifies host-process preflight and missing representative workload/physical-work oracles; these cannot be promoted by increasing duration alone. Focused validation completed below; no source/ledger repair justified by the assigned failure.

## Commands and outcomes

All commands executed locally in the assigned worktree with long timeouts.

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1332 reviewed identities match 1332 findings; no unbanked identity |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; historical 24-vs-21 DDL failure absent |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3105 files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 28173 unique test identities, no duplicate evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python -` importing the current runner and evaluating preserved `evidence/m3a-round6-shakedown.json` | Observed duration 90.43 seconds; failures `sustain_duration`, `exact_rc_artifact`; assertions verified both failures and unconditional preflight artifact rejection |

No new live soak or PostgreSQL integration run was executed. The last command
re-evaluates historical evidence, not new production observations. No tests
changed or were added, so no inventory-delta note is necessary.

## Architecture and acceptance review

Accepted ADR-081226-69ee retains Graph/Run/NodeRun/Attempt; accepted
ADR-081626-f383 assigns lease/fence authority to the canonical Run store and
explicitly does not establish lease-expiry takeover. Neither admission identity
nor a restarted process proves physical-work recovery. No competing execution,
event, Goal or authorization authority was introduced.

Accepted ADR-085 requires principal-keyed limiting. Production middleware
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30`) explicitly
retains independent per-process state. That implementation contract is not a
waiver of #860's stronger replica-selection acceptance. The passing production
middleware tests reproduce the gap, not a cluster-wide budget. ADR-081 is
Proposed; it cannot authorize substituting preflight evidence for an exact RC.

| Acceptance criterion | Executed evidence / disposition |
|---|---|
| Representative RC workload | Profile inspected; it explicitly lacks concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and background reconciliation. Complete applicability UNVERIFIED. |
| At least two supported production replicas | Tests instantiate two actual middleware instances via ASGI; not two deployed RC applications. Production topology exercise UNVERIFIED. |
| Sustained saturation, reclaim, retries and leaks | Real child-process sampler regression passes. No long-window application load executed; UNVERIFIED. |
| No duplicate physical work across replicas | Admission probe's invalid/replayed receipt tests and task router/backpressure test pass, but do not execute cross-replica physical Attempts or Goal reconciliation. UNVERIFIED. |
| Rate/security/degraded non-bypass | `tests/test_soak_promotion_gates.py:439-488` observes `[200, 200, 429]` independently on each replica for the same identity, authenticated and unauthenticated. Replica-selection non-bypass NOT MET; sustained security/degraded behavior UNVERIFIED. |
| Complete telemetry with explicit thresholds | Sampler tests pass; `scripts/soak/run_soak.py:1523-1585` evaluates a subset. Complete application-loop, pool/worker and long-window error/leak coverage UNVERIFIED. |
| Restart during active work, drain/fence/recover | Cleanup/boot tests pass; no live active-work kill/restart with Attempt-level correlation executed. UNVERIFIED. |
| Long-running exact RC artifact/config soak | NOT MET by available evidence: evaluator rejects the 90.43-second preflight. `scripts/soak/run_soak.py:686-697` rejects host-process equivalence regardless of duration. |
| Findings filed/reclassified before promotion | Backlog consistency passes; external filing/classification completeness UNVERIFIED. No GitHub mutations. |
| Publish hash-bound machine/human promotion evidence | Existing profile/JSON are historical preflight artifacts, not a fresh immutable RC/config soak; UNVERIFIED. |

## Handoff

**BLOCKED** for issue acceptance, not a current reproduction of the assigned CI
failure. `packages/maistro-core/tests/persistence/test_pg_learnings.py:173-177`
already asserts the three evaluator audit columns absent in the historical log.
The exact debt scan balances, so changing the ledger would be speculative.
Only this report changed. Existing implementation and evidence were preserved.

Next prerequisites: identify the immutable RC image and normalized configuration;
resolve representative workload applicability and the rate-budget mismatch;
implement production-path physical-work/recovery oracles, then run the required
fresh >=4-hour exact-artifact soak. A longer host preflight cannot satisfy the
artifact gate. Do not dispatch the same historical schema failure as a new
source repair without fresh failing evidence.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: RC prerequisites}.
Focused CI validation is complete; release acceptance remains incomplete. This
report is committed locally; no integration approval or issue closure implied.
