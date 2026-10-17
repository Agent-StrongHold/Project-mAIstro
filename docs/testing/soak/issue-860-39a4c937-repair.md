# Issue #860 — repair validation (job 39a4c937)

## Frozen scope and initial checkpoint

- Assigned item: #860 only, branch `auto-860`, starting HEAD
  `6924a7a75a82a8e9630bdd6b6dc75758c0c1abda`; supplied develop base
  `1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4` resolves locally.
- Starting worktree is clean; no incoming diff needs salvage.
- Scope: existing soak runner/profile/evidence and promotion tests; adjacent
  task-admission, PostgreSQL learnings, and rate-limit implementation/tests;
  relevant ADRs/instructions; exact vulture gate and its ledger only if it fails.
  Planned write: this validation/handoff note. No unrelated branch changes.
- Executed exact vulture command:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1,355 findings, 1,355 reviewed identities, zero unclassified.
  No guessed identity fixes or unnecessary ledger amendment are justified.
- Job directory snapshot has no `check-*.log` files. Driver check claims cannot
  be independently inspected here. Prior job result was read, not accepted as
  fresh validation.
- Assumption: this is the writer repair lane, not read-only verification.
  Historical host-process shakedowns cannot satisfy an exact deployed RC soak.
  RC artifact/configuration selection is not supplied by the lane brief.

## Validation checkpoint

Executed with 600-second timeout:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,836 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped**. The skips require `MAISTRO_TEST_PG_DSN`; they
  are not PostgreSQL concurrency proof.

Read the existing profile, human evidence, adjacent promotion regressions,
production middleware, production Compose and artifact evaluator. The old H3
shared-store contradiction is already corrected: current human evidence calls
it partial and explicitly states independent replica budgets. Both authenticated
and unauthenticated middleware regression cases executed successfully, proving
an exhausted first replica does not exhaust the second replica's allowance.

Read accepted ADR-085, ADR-081626-f383, ADR-082526-b36a, and ADR-082426-82c7.
Reconciliation: per-principal identity is not proof of a shared cluster budget;
canonical occurrence admission and durable Attempt fencing are not proof that
physical work never duplicates during a live failure. No competing execution or
authorization mechanism is introduced. ADR-081 is Proposed, not accepted
architectural authority; the shipped Compose supplies the two-replica claim.
Compose requires a model gateway and pg17; historical host-process preflight
used pg18 without a provider. These cannot be declared equivalent artifacts.

No runtime, configuration, test, ledger or historical evidence changes are
justified by these checks. This documentation-only checkpoint adds no tests;
inventory delta is zero.

## Additional executed checks

All used a 600-second timeout:

- `uv run python scripts/check-suite-inventory.py`: PASS, all 14 suites match.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `git diff --check`: PASS.
- Inline `uv run python` imported the current runner, loaded the four frozen
  historical packs and asserted each fails both `sustain_duration` and
  `exact_rc_artifact`: PASS. Round 5 reports 90.17 seconds; round 6 reports
  90.43 seconds. The original and repair-validation packs lack top-level
  `sustain_seconds`. Also asserted `preflight_artifact_check()['ok'] is False`.
  This re-evaluates historical evidence; it is not a new soak.

## Acceptance accounting

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC load profile | PARTIAL: inspected profile documents a request mix and thresholds but explicitly lacks multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/worker coverage. RC applicability UNVERIFIED. |
| 2 | At least two deployed application replicas | Compose inspection and boot-contract tests confirm the declared topology, not a live RC deployment. UNVERIFIED. |
| 3 | Sustained saturation, queues, reclaim, backoff, leaks, shutdown | UNVERIFIED; inspected round-6 evidence is 90.43 seconds versus 14400 required. No new load ran. |
| 4 | No duplicate physical work across replicas | UNVERIFIED; admission-probe regressions pass, but physical effects and Goal reconciliation during live failure are not proven. |
| 5 | Rate/security/degraded non-bypass | Independent middleware allowances reproduced for both identity classes. Cluster-wide non-bypass is UNMET; complete RC security/degraded behavior UNVERIFIED. |
| 6 | Complete production metrics and explicit thresholds | PARTIAL: live-child sampler regression passes; application-loop, detached-worker and full production measurements remain UNVERIFIED. |
| 7 | Active-work kill/restart, drain/fencing/recovery | UNVERIFIED; process rejoin and terminal counts do not prove correlated physical-work recovery. |
| 8 | Long-running exact RC artifact/config soak | UNMET: all four historical packs rejected by current evaluator; host runner explicitly cannot certify the production artifact. No immutable RC manifest supplied. |
| 9 | Findings filed/reclassified to earliest invariant | PARTIAL: inspected local F-series classifications. External filing UNVERIFIED; GitHub mutations forbidden. No new load findings discovered here. |
| 10 | Human/machine evidence with exact image/package/commit/config hashes | Historical packs exist; qualifying RC evidence UNVERIFIED. This note is validation, not soak evidence. |

## Final handoff

**BLOCKED.** Sole changed file: this note. No unbanked vulture identity exists
at the assigned head, so the conditional CI ledger repair needs no amendment.
No sync conflict exists. The prior blocker is not resolved by passing static
checks or by running the same host emulator longer.

Next requires release-owner selection of immutable RC image/configuration and
actual provider/services, completion of representative production workloads and
metrics, resolution of replica-selection rate-budget semantics with canonical
policy owners, and a >=14400-second exact-artifact soak with physical-effect
correlation during recovery. Any code/runtime-config change requires re-soaking.
Do not repeatedly schedule this unchanged CI-repair lane as a substitute.

Progress: checked 1; acceptance-complete 0; skipped items 0; command errors 0;
blocked 1. Commit this checkpoint locally; no push or GitHub mutation. Residual
risk is missing release evidence, not a newly evidenced ledger defect.
