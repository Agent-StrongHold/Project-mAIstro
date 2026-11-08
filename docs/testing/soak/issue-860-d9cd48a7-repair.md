# Issue #860 — bounded CI repair d9cd48a7

## Frozen scope

- Issue #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `adbcb0b50ed6f89ed8a201ef434e809e72ba3240`; supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Starting worktree clean.
- Inputs: supplied dispatch-context.json, prior result 18b86dab, cited
  98a11313/check-3.log. No check-*.log exists in this job directory.
- Repair targets are this report and quality/vulture-baseline.json only if the
  required exact scan demonstrates reviewed retained identities. Inspect the
  implicated production files and adjacent tests before any ledger amendment.
- Acceptance validation scope: existing soak runner, promotion tests, load-profile
  documentation, relevant ADRs, and implicated package tests. No new execution
  authority or authorization path; no GitHub mutations or ref refresh.
- Ambiguity: the prior result is BLOCKED, not a develop-sync conflict. Proceed
  with the explicit CI-repair instruction; do not merge unrelated work.

## Progress

- Required exact vulture scan executed successfully: 1323 reviewed identities,
  1323 findings, zero unclassified/never-allowlist findings. No ledger change is
  supported by evidence.
- Cited historical check-3.log reports 24 schema DDL statements versus 21 expected.
  The current test independently lists all 24, including Gauntlet audit columns.
  Executed the learning-store, soak-promotion, task-backpressure and production
  boot-contract tests together: **111 passed, 6 skipped**. Historical failure
  does not reproduce. This is unit/regression evidence, not an RC load run.
- Read the current load profile: it explicitly excludes required representative
  traffic and identifies its host-process topology as preflight only. Exact-RC
  acceptance remains unresolved; do not substitute another short emulator run.

## Architecture reconciliation

Read repository AGENTS.md, docs/README.md and accepted ADR-081226-69ee,
ADR-081626-f383 and ADR-082126-f69c. Preserve Goal -> Graph -> Run -> NodeRun ->
Attempt; recurrence admits Runs, not a second runtime. ADR-081626-f383 explicitly
excludes lease-expiry takeover from its current fencing contract. The issue's
reclaim wording cannot authorize inventing timeout-based execution authority.
No production, tests, inventory or ledger changes were warranted this round.

## Executed validation

All commands ran in the assigned worktree with 1200-second tool timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323; output `/tmp/860-d9cd48a7-vulture.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 111 passed / 6 skipped; output `/tmp/860-d9cd48a7-pytest.log`. Skips are not acceptance evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 31128 unique test identities, no duplicate evidence. No tests added, so no inventory delta.
- `uv run python` loaded `scripts/soak/run_soak.py` and evaluated existing
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: asserted failures are
  exactly `sustain_duration` and `exact_rc_artifact`; PASS. Recorded duration
  420.08 seconds, required minimum 14400. Also asserted the current preflight
  artifact check is false. This evaluates historical evidence, not a new soak.

## Acceptance matrix

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Read `m3a-load-profile.md:152`: missing multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background traffic. |
| Two production RC application replicas | **UNVERIFIED.** Passing boot-contract and middleware tests do not deploy two immutable RC containers. |
| Sustained saturation, queue growth, reclaim, retry and leaks | **UNVERIFIED.** Historical 420.08-second evidence fails the current duration gate. Process sampler regression passes, but is not sustained application-load evidence. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without physical execution. Admission identity tests cannot prove physical Attempt uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall, contrary allowance evidence reproduced.** `tests/test_soak_promotion_gates.py:439` uses real production middleware: the same principal receives `[200, 200, 429]` independently on both instances, for both authentication classes. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` explicitly documents process-local policy. |
| Complete telemetry with thresholds | **UNVERIFIED.** Profile distinguishes driver loop lag and SELECT 1 latency from application loop/query latency; no current long-window RC telemetry collected. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** Passing boot cleanup and evidence-gate tests do not execute this scenario on deployed active work. |
| Long soak of unchanged exact RC artifact/configuration | **UNVERIFIED / BLOCKED.** `scripts/soak/run_soak.py:730` rejects its host preflight. Existing historical evidence fails artifact and duration checks. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED externally.** Limitations recorded locally; no GitHub mutation authorized or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED.** Historical preflight evidence is not current immutable RC identity evidence. |

## Disposition and handoff

**BLOCKED.** The supplied CI failure is stale at this HEAD and the exact vulture
scan is green. Amending reviewed identities without any scan delta would be
cosmetic, not a repair. Only this report changes; local commit required, no push.

Next needs a designated immutable RC image/configuration and a production-topology
runner covering representative physical-work workloads and telemetry, followed by
active-work restart and at least four hours of unchanged RC load. The local rate
policy also needs explicit reconciliation with replica-selection acceptance.
Repeated unit checks cannot replace those prerequisites. No develop-sync conflict
was present, so no fetch or merge was performed.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
Here `done` means issue acceptance completed; bounded CI investigation is complete.

