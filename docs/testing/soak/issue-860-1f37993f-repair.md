# Issue #860 — bounded CI repair validation

## Frozen scope

Job `1f37993f3a264768bd269e1c3b4cb4b6`; writer; worktree `auto-860`.
Starting HEAD `addf832c0b33f3e8b98982575931aed4ed3aefd8`, clean.
Base `9bd1a93eefc4e564041b3cc512f20b229cde64b9`.
Only issue #860 is processed; no linked PR or issue work is admitted.

Fixed inspection scope: supplied dispatch snapshot and prior failure/result;
repository instructions and applicable ADRs; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, load profile and preserved evidence;
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` and its tests;
`packages/maistro-server/src/maistro_server/api/tasks.py` and backpressure tests;
production rate middleware; exact vulture checker, CI arguments, and ledger.
Potential edits are limited to evidence-backed fixes in those files, associated
inventory notes, and this report. Ledger changes only for observed identities.

Initial evidence: no `check-*.log` files exist in this job directory. Supplied
prior `98a11313.../check-3.log` reports 24 schema DDL calls versus 21 expected;
this is historical evidence, not yet a reproduced current failure. Prior result
is BLOCKED and does not establish current correctness. Assumption: this is a
writer CI-repair round, not authorization to replace the deployment contract or
invent an RC artifact. No GitHub mutations, production deployment changes, or
changes to execution/authorization authorities are permitted.

## Results

- Exact requested vulture command passed: 1332 reviewed identities / 1332
  findings, zero unclassified or forbidden findings. No unbanked identity exists
  to amend; speculative ledger changes are not justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. Historical check-3 failure is not reproduced;
  the expected DDL already includes all three evaluator audit columns.
- Load profile explicitly declares the host-process runner non-promotable and
  lists representative traffic gaps. A longer preflight cannot resolve them.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3105 files).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 73 tests. This exercises production middleware through ASGI, the task
  router/admission spine and a real subprocess resource sampler, not an RC soak.
- `uv run python scripts/check-suite-inventory.py` passed: 17 suites, 28173
  unique identities, no duplicate evidence. No tests added or changed, so no
  inventory delta is required.
- `uv run python scripts/check-backlog-consistency.py` passed: 168 items.

Architecture: accepted ADR-081226-69ee retains Graph/Run/NodeRun/Attempt;
ADR-081626-f383 gives the canonical Run store fencing authority. Admission
identity alone does not establish physical-work recovery. ADR-085 specifies
per-principal limiting; middleware explicitly documents independent per-process
allowances (#842). The executed replica-selection tests reproduce that behavior,
not #860's stronger non-bypass claim. No new authorization or execution authority
is introduced to reconcile the gap. ADR-081 is Proposed and cannot waive exact
RC evidence. No merge conflict exists and the supplied prior block concerns
release prerequisites, not develop synchronization.

The current evaluator was imported and executed against preserved
`evidence/m3a-round6-shakedown.json`: duration 90.43 seconds; failed gates
`['sustain_duration', 'exact_rc_artifact']`. Assertions confirmed both failures
and `preflight_artifact_check()['ok'] is False`. Historical evidence was not
modified. This evaluates existing evidence; it is not a new soak.

## Acceptance disposition

| # | Criterion | Evidence and disposition |
|---|---|---|
| 1 | Representative RC workload | Profile reviewed; concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and background work remain explicitly missing. Complete applicability UNVERIFIED. |
| 2 | Two production application replicas | Production middleware instantiated twice in passing ASGI tests. No deployed exact-RC replica pair exercised this round; UNVERIFIED. |
| 3 | Sustained saturation/reclaim/retry/leaks | Real subprocess sampler regression passes. Long-window application behavior UNVERIFIED; no sustained run executed. |
| 4 | No duplicate physical work | Passing HTTP admission oracle and real task-router/spine backpressure tests do not establish cross-replica physical Attempt fencing or Goal reconciliation. UNVERIFIED. |
| 5 | Rate/security/degraded non-bypass | `tests/test_soak_promotion_gates.py:439-488` executes production middleware and observes `[200,200,429]` independently on each replica for the same authenticated/unauthenticated identity. Non-bypass NOT MET; sustained security/degraded behavior UNVERIFIED. |
| 6 | Complete telemetry and thresholds | Sampler tests pass; `run_soak.py:1523-1585` records selected checks. Application-loop latency and complete pool/worker/leak/error thresholds under RC load remain UNVERIFIED. |
| 7 | Kill/restart during active work | Boot/cleanup and evidence-gate tests pass; no active-work production kill/restart with physical Attempt correlation executed. UNVERIFIED. |
| 8 | Long-running exact RC soak | NOT MET: executed evaluator rejects the preserved 90.43-second preflight. `run_soak.py:686-697` explicitly rejects host-process artifact equivalence regardless of duration. |
| 9 | Findings filed/reclassified | Human pack records F1–F12; backlog gate passes. External filing completeness UNVERIFIED; no GitHub mutations performed. |
| 10 | Hash-bound machine/human promotion evidence | Preserved human/JSON evidence exists, but is historical preflight evidence, not a current immutable RC/config soak. UNVERIFIED. |

## Handoff

**BLOCKED** for issue acceptance. The assigned CI failure is already repaired at
starting HEAD, and the exact debt ledger balances. There is no evidence-backed
source or ledger repair to perform in this round. Only this report changed;
no tests, inventory counts, runtime configuration or production code changed.

Next: release owner must identify immutable RC image/configuration and approve
representative workload applicability; the production runner needs physical-work,
security and recovery oracles. Resolve the documented rate-budget mismatch, then
execute a fresh >=4-hour exact-artifact soak after runtime changes. Repeating
this already-passing historical CI failure cannot satisfy those prerequisites.
No full-tree pytest or live PostgreSQL tests were claimed (six DB tests skipped).

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: RC prerequisites}.
Focused CI validation is complete; release acceptance is not. Finalize this
report with a local commit; no integration approval or issue closure implied.
