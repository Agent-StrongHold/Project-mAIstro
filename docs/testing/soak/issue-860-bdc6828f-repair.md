# Issue #860 repair — bdc6828f

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`eb7f5fce7d32804c7216ce83d5b88c9d9c13f198`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial worktree was clean. No synchronization conflict was present.
Process the requested vulture CI repair and validate existing soak acceptance;
do not process linked issues/PRs or invent a release candidate.
Candidate edit surfaces: this report, `quality/vulture-baseline.json` only if
actual scan evidence requires its explicitly authorized amendment. Production
soak scripts and adjacent tests are inspection/validation surfaces, not a new
scheduler implementation.

## Initial evidence

The supplied prior result is BLOCKED, not acceptance proof. The current job
directory contains no `check-*.log` at initial inspection. Read the explicitly
referenced prior failed log separately. Ambiguity: no designated RC artifact or
runtime configuration is included in the assignment; do not substitute local
host smoke tests for an exact-RC soak.

## Executed results

- Requested vulture command passed: 1323 findings / 1323 reviewed identities,
  zero unclassified or never-allowlist findings. It selected base `4aa68edc0b6b`.
  There is no demonstrated ledger defect; no ledger amendment is justified.
- The supplied historical `98a11313/check-3.log` contains a failing schema-fence
  test (24 DDL statements vs 21 expected), not a vulture failure. Reproduce the
  current schema tests before considering any repair.
- `docs/testing/soak/README.md`: not found; skipped. Inspected the actual soak
  script and its adjacent promotion-gate tests instead.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`: **102 passed, 6 skipped** (2.21s).
  Historical schema failure does not reproduce. Skips are not acceptance proof.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  31128 unique test identities, no duplicate evidence.
- `git diff --check`: passed.

## Architecture and actual coverage

Read repository instructions, documentation authority hierarchy, accepted
ADR-081226-69ee (Graph/Node execution), ADR-081626-f383 (Attempt leases/fences),
and ADR-082126-f69c (recurrence produces Runs), including the superseded
ADR-046. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing
scheduler, authority, store, or authorization path is introduced. In particular,
the lease ADR does not itself authorize expiry takeover. Admission identity is
not evidence of unique physical work or successful reclaim.

Current code at `scripts/soak/run_soak.py:730` returns false for exact RC
artifact equivalence. Executed tests reject four-hour synthetic preflight
results when artifact evidence is missing/null/preflight. At line 1044 the
schedule probe cancels an admitted Run explicitly without execution.
`tests/test_soak_promotion_gates.py:439` exercises real rate middleware for both
identity classes and observes `[200, 200, 429]` independently on two instances;
this is contrary evidence for a shared allowance, not proof of a deployed
cluster. No source or ledger defect implicated by the supplied failed command
remains reproducible in this round.

Additional executed validation:

- `uv run pytest tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **9 passed** (1.77s).
- `uv run python` imported the current soak evaluator and asserted the failed
  gates for `docs/testing/soak/evidence/m3a-round30-shakedown.json` were exactly
  `sustain_duration` and `exact_rc_artifact`; passed. Observed duration is
  420.08 seconds, below 14400 seconds. Also asserted the current preflight
  artifact check is false. This re-evaluates historical data, not a fresh soak.

## Acceptance, checked individually

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Profile exists, but `m3a-load-profile.md:152` lists absent multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/background workloads. No immutable RC inclusion/exclusion contract supplied. |
| At least two deployed replicas | **UNVERIFIED for RC.** Boot-contract tests pass; host emulator and ASGI tests are not deployed production image evidence. |
| Sustained saturation, queue, reclaim, retry and leak observations | **UNVERIFIED.** Historical 420.08-second sample fails the current duration gate. No long-window production run executed. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED.** Admission tests pass, but schedule probe explicitly never executes its admitted Run (`run_soak.py:1044`). No physical-work or Goal soak proof. |
| Security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall, contrary rate evidence reproduced.** Actual production middleware has independent allowances (`test_soak_promotion_gates.py:439`; `api/rate_limit.py:32,93`). Direct 429 observations do not prove a shared budget. |
| All required telemetry with thresholds | **UNVERIFIED.** Real child-process sampler regression passes; driver lag and SELECT 1 latency are not application loop/query telemetry. Profile explicitly leaves worker counts, saturation and long-window observations unproven. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Cleanup/boot tests pass; process rejoin and terminal Run counts alone cannot prove physical-work fencing. No deployed active-work kill executed. |
| Long soak of unchanged exact RC | **UNVERIFIED / BLOCKED.** Current host artifact check always fails; historical evaluator rejects duration and artifact. Designated RC image/configuration and production runner evidence are missing. |
| Findings filed/reclassified before promotion | Local limitations are recorded here and in the existing evidence pack. External milestone disposition **UNVERIFIED**; no GitHub mutations permitted or performed. |
| Publish machine/human evidence tied to exact hashes | Historical preflight JSON and human pack exist but explicitly disclaim promotion proof. Exact-RC evidence **UNVERIFIED**. |

## Handoff

**BLOCKED**, not merge-ready. The requested CI scan and historical failing test
are now freshly checked and passing; do not amend a matching ledger or weaken
tests to manufacture a repair. Only this report changed. No tests added or
removed, so no inventory delta note is required; inventory gate passed.

Next: supply the designated immutable application image/configuration and a
production-topology runner with representative workloads, physical Attempt
and Goal correlation, full telemetry, and an active-work restart protocol;
resolve the replica-selection policy discrepancy before the at-least-four-hour
exact-RC soak. A longer execution of the existing preflight cannot close this
block. Do not mistake repeated validation-only rounds for acceptance progress.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
The one assigned issue was checked and remains blocked; the exact-RC run was
not attempted. Commit this report locally; no push, PR or closure action.

