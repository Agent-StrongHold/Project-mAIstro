# Issue #860 repair checkpoint — c72601c4

## Frozen scope

Only issue #860, branch `auto-860`, starting at
`d447a5cd175a8e0c5aa56db1ece75ba4b6bab19a`, supplied base
`2a11c1cc006a977ee76281307767319773d4fb62`.
Initial working tree was clean; no salvage needed.

Process the supplied schema-fence failure and explicit exact-debt-ledger CI
repair, then check existing promotion evidence. Candidate edit scope is
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`quality/vulture-baseline.json` only for actual reviewed scanner findings,
this report, and an inventory note if tests change. No production execution
or authorization redesign is authorized by this repair.

The current job directory contains no `check-*.log`. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements
against 21 expected. This is historical evidence, not a current failure.
The prior result reports BLOCKED on exact-RC evidence and shared rate budgets;
these claims require fresh checks. Assumption: the assignment is a writer
repair, not the generic read-only verifier role in the prompt.

## Fresh checkpoint

- Exact requested vulture command passed: 1,326 findings, 1,326 reviewed
  identities, zero unclassified and zero never-allowlist findings. No ledger
  amendment is justified; the explicit repair exception does not require
  inventing debt.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. The supplied historical failure is already
  repaired by the three explicit Gauntlet column assertions at lines 173–177.
  Skipped database tests are not evidence of live replica safety.

No current CI failure has been reproduced. Acceptance inspection follows;
no production, test or ledger edit will be made without evidence.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,170 files).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  100 passed. This includes the actual production limiter instantiated twice:
  the same identity receives `[200, 200, 429]` independently from each replica.
  These are in-process ASGI checks, not a deployed soak.

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and
ADR-073126-c4e1. Reconciliation: physical execution identity is Attempt, not
Run admission. Lease renewal/reclaim now has a canonical implementation
contract; the earlier fencing ADR's historical boundary is not a waiver.
Promotion needs the selected immutable RC, not a host-process substitute.
No execution, event, Goal or authorization authority is changed.

## Final validation

- `uv run python -` imported the current soak driver and reevaluated
  `evidence/m3a-round30-shakedown.json`: actual duration 420.08 seconds;
  failed gates exactly `sustain_duration` and `exact_rc_artifact`.
  Assertions requiring both failures and rejecting the current host topology
  passed. This rechecks historical evidence; it does not execute a new soak.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  29,499 unique test identities, no duplicate evidence.
- `uv run python scripts/check-merge-markers.py`: passed.
- `git diff --check`: passed.
- Test/gate commands used 1,200-second timeouts. No tests changed or added,
  so no inventory delta is needed. Only this report changed.

## Acceptance disposition

| Criterion | Executed evidence / gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** `m3a-load-profile.md:153-172` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker work. No selected RC configuration establishes exclusions. |
| At least two deployed application replicas | **UNVERIFIED.** Two limiter instances were tested; no deployed RC replicas were exercised in this round. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, memory/descriptor/process leak and shutdown observations | **UNVERIFIED.** The historical 420.08-second run fails the 14,400-second minimum. Measurement tests do not prove production behavior over that window. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | **UNVERIFIED.** Admission checks are not physical execution checks under ADR-081426-1f7c. No active Attempt effects or Goal reconciliation observed across deployed replicas. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven; shared-budget interpretation fails.** Executed `tests/test_soak_promotion_gates.py:439-488` demonstrates independent allowances for authenticated and unauthenticated identities. The tested middleware is installed by production `main.py:648`; `api/rate_limit.py:31-37` documents process-local scope. Broader deployed security remains **UNVERIFIED**. |
| PostgreSQL connection/query/lock, application-loop, worker/process/RSS/fd/queue/error/timeout telemetry and thresholds | **UNVERIFIED complete.** The profile defines thresholds, but this round collected no production telemetry. Driver loop lag is not application loop lag. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Passing boot cleanup tests are not physical-work takeover or stale-effect rejection evidence. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** Current code rejects the historical duration and host artifact. `run_soak.py:730-741` deliberately reports host preflight as insufficient. No immutable RC artifact/configuration was selected by this brief and no four-hour RC run was executed. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** No new load execution or remote mutations; historical classifications cannot prove completeness for a new RC. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for candidate.** Preserved historical evidence cannot certify this HEAD. This report is validation evidence only, not a promotion evidence pack. |

## Handoff

**BLOCKED.** The concrete supplied CI failure is already fixed and the requested
scanner supplies no debt to amend. No repair to production or tests is justified
by the current results. Repeating this CI-repair dispatch cannot supply the
missing release acceptance evidence.

Next action requires a selected immutable RC artifact/configuration, representative
production-path workload and telemetry, resolution of the replica-budget
acceptance mismatch through the existing security seam, then at least four hours
of load with active-work recovery/fencing and hash-bound evidence. Do not extend
the host preflight and relabel it as exact-RC proof. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt` throughout.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and production acceptance execution"}`.
This report is committed locally; no push, PR, merge or issue mutation.

