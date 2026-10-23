# Issue #860 — CI repair checkpoint (3c9473b6)

## Frozen scope

Writer repair of #860 only, in `auto-860`, starting at
`c9afdb1d870b64db34b55df0bcf01491240ec3f5`, supplied base
`2b23303f72f028a5dbcf9da82bb755496587a8ad`. The worktree was clean.
No GitHub mutation or integration approval is authorized.

Process the supplied schema-fence failure, the explicit vulture ledger repair,
and acceptance evidence for this issue only. Candidate edits are
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`quality/vulture-baseline.json` for actual reviewed scanner findings, this
report, and an inventory note only if tests change. Do not invent ledger debt
or redesign execution/security based on historical claims.

The current job directory has no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements
against 21 assertions. Prior result `c72601c4` reports that failure already
fixed, a passing vulture scan, and missing production soak evidence. These are
historical claims pending fresh validation. Assumption: writer repair role
applies, not the generic verifier prohibition on editing.

Read repository instructions and the full issue acceptance from the supplied
dispatch snapshot. The existing profile explicitly calls the harness a
host-process preflight, not the promoted artifact. No RC image/configuration
is selected in the assignment. Preserve the canonical execution model
`Goal -> Graph -> Run -> NodeRun -> Attempt`.

## Validation

- The exact requested vulture command passed: 1,326 findings matched 1,326
  reviewed identities, zero unclassified and zero never-allowlist findings.
  CI uses these same scan arguments. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The supplied failure is already repaired:
  lines 175–177 explicitly assert all three Gauntlet schema additions inside
  the transaction fence. PostgreSQL-dependent skips do not prove live safety.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,170 files.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **100 passed**. These are focused gate/ASGI/boot tests, not a deployed soak.
- `uv run python -`: imported the current soak driver and reevaluated
  `evidence/m3a-round30-shakedown.json`. Actual duration: 420.08 seconds;
  failed gates: `sustain_duration`, `exact_rc_artifact`. Assertions requiring
  both failures and rejecting the current host topology passed. This checks
  historical evidence; it does not execute a new soak.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  29,499 unique test identities, no duplicate evidence.
- `uv run python scripts/check-merge-markers.py`: passed.
- `git diff --check`: passed.

All validation commands used 1,200-second timeouts. No tests were changed or
added, so there is no inventory delta. Only this report changes. No current CI
defect was reproduced, so production code, tests and the ledger remain intact.

## Architecture reconciliation

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and
ADR-073126-c4e1. Physical execution identity is the Attempt, not Run admission.
The later renewal/reclaim contract supersedes the earlier fencing ADR's
historical deferral of reclaim; it is not an acceptance waiver. Exact-RC
promotion requires the selected immutable artifact/configuration, not a host
emulator. No alternate scheduler, execution, event, Goal or authorization
mechanism is introduced.

## Acceptance disposition

| Issue criterion | Fresh evidence / unresolved gap |
| --- | --- |
| Representative release-candidate load profile | **UNVERIFIED complete.** `m3a-load-profile.md:153-172` acknowledges missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workers. No selected RC configuration justifies exclusions. |
| At least two application replicas | **UNVERIFIED for RC.** Two independent production middleware instances ran in ASGI tests, not two deployed RC replicas. |
| Sustained saturation, growth, expiry/reclaim, retry/backoff, leaks and shutdown observations | **UNVERIFIED.** Reevaluated historical evidence is only 420.08 seconds and fails the profile's 14,400-second minimum; no new long-window production observations. |
| No duplicate schedule/task/Run/Attempt/Goal physical work across replicas | **UNVERIFIED.** Admission/receipt checks and fake-connection schema checks cannot establish physical Attempt uniqueness, fenced effects or sustained Goal reconciliation. |
| Concurrent rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as stated.** `tests/test_soak_promotion_gates.py:439-488` freshly passes by observing `[200, 200, 429]` independently on both replicas for the same authenticated/unauthenticated identity. The production middleware is installed at `packages/maistro-server/src/maistro_server/main.py:648`. Its documented process-local contract (`api/rate_limit.py:32-37`) permits N times the configured allowance; a shared-budget reading of acceptance is contradicted, not proven. Broader deployed security remains unverified. |
| Complete PostgreSQL/loop/workers/RSS/fd/queue/error/timeout telemetry with thresholds | **UNVERIFIED complete.** Profile defines thresholds, but no candidate production telemetry was collected; driver loop lag is not application loop lag. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup tests and historical process rejoin do not prove physical active-work takeover or stale-effect rejection. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** Current `scripts/soak/run_soak.py:730-741` explicitly rejects its host preflight. Historical evidence freshly fails both artifact and duration gates. No immutable RC image/configuration is selected by this assignment and no four-hour RC run was executed. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** No new load campaign or remote mutations; historical findings cannot establish completeness for a new RC. |
| Machine/human evidence bound to exact artifact/configuration hashes | **UNVERIFIED for candidate.** Historical packs are preserved, but do not certify this HEAD. This report is validation evidence only. |

## Handoff

**BLOCKED.** The concrete supplied test failure is already fixed and the exact
scanner reports no unbanked identities. Neither warrants a speculative repair.
Do not redispatch this same historical CI failure as though it were current.

Next action needs a selected immutable RC artifact/configuration, representative
production workload and telemetry, an explicit resolution of the replica-budget
acceptance mismatch through the existing security seam, then at least four hours
of active-work load/recovery/fencing with hash-bound evidence. Extending or
relabeling the host preflight cannot meet that condition. No gates were weakened
and no ledger/grants amended.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and production acceptance execution"}`.
Report committed locally; no push, PR, merge or issue mutation.
