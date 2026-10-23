# Issue #860 — repair checkpoint (173bf0f2)

## Frozen scope

- Issue: #860 only; writer lane, worktree `/home/dev/Git/wt/auto-860`.
- Starting head: `2172e3011407572a1d56e8f58dc24703e2fd1015`.
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting tree clean; no incoming uncommitted work to salvage.
- Evidence inputs: this job's dispatch-context.json, supplied prior result,
  supplied check-3.log, repository instructions, relevant execution ADRs,
  scripts/soak/run_soak.py and its adjacent tests, CI vulture gate and ledger.
- Edit scope: this report; soak code/tests and required inventory note only if
  reproduced evidence supports a focused repair; quality/vulture-baseline.json
  only for actual scanner identities under the explicit CI-repair exception.
- No GitHub mutations, new execution authority, or promotion approval.

## Initial observations

The assigned job directory contains no check-*.log files at start. The supplied
prior result reports BLOCKED, not successful RC acceptance. That claim will be
checked against current source and fresh validation rather than assumed true.
The inherited branch contains substantial prior work, which is preserved.

Ambiguity: the generic prompt includes verifier and writer instructions. The
explicit repair assignment and mandatory local commit identify this as writer
work. Only issue #860 is being processed; linked PRs are evidence, not new items.

## Fresh validation checkpoint

- Exact requested vulture command passed: 1,323 findings / 1,323 reviewed
  identities, zero unclassified or never-allowlist findings. No ledger amendment
  is justified: the reported CI-debt failure is not present at this head.
- Supplied historical check-3.log failed on 24 emitted DDL statements versus 21
  expected statements. The current test independently enumerates all 24,
  including the three Gauntlet audit columns; production keeps them inside the
  advisory-locked transaction. Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed:
  **37 passed, 6 skipped**. Skips are not PostgreSQL integration evidence.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,270 files formatted.

Read accepted ADR-081226-69ee, ADR-081426-1f7c and ADR-081626-f383.
Reconciliation: admission uniqueness cannot stand in for physical Attempt
fencing; the lease ADR explicitly does not by itself define expiry takeover.
No new scheduler, lease authority, or alternate execution model is introduced.

No production code/test change is justified by the supplied stale failure or
the clean scanner. The linked PR bodies and latest captured issue comments
supply no promotion approval or new exact-RC run to validate.

## Completed commands

All commands used the assigned worktree and the existing uv environment, with
1,200-second validation timeouts. In addition to the commands above:

| Command | Observed outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323/1,323 identities; matches both CI workflows' arguments |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 82 tests |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; delegated checks pass; two non-fatal invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `uv run python scripts/check-test-duplicates.py` | PASS, 1,585 unique test files |
| `git diff --check` | PASS |

The ratchets selected their existing automatic base `4aa68edc0b6b`, not the
assigned campaign base; no base ref or authorization was changed. These results
are deterministic checks, not soak acceptance. No tests were added or changed,
so the inventory delta is zero and no new inventory note is needed. The full
monorepo pytest suite was not run. The six PostgreSQL-gated skips remain explicit.

## Acceptance matrix (all ten issue criteria)

| Criterion | Current evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:152` names missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and background-work coverage. `run_soak.py:1373` uses one credential and the mix at 1381 contains health, task admission, fabricated receipt reads and unauthenticated metrics, not those workloads. |
| At least two supported production replicas | **UNVERIFIED at RC grade.** `run_soak.py:730` explicitly classifies the runner as host-uvicorn preflight. ASGI limiter instances in passing tests are not deployed replicas. No exact production deployment was started this round. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED.** No fresh long-window load was run; passing short unit/regression tests cannot supply saturation, lease reclaim or leak evidence. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044` cancels the queued schedule probe without execution. Receipt identity tests prove admission accounting, not physical Attempt uniqueness, fencing or sustained Goal reconciliation. |
| Rate/security/degraded non-bypass | **NOT PROVEN.** Passing production-middleware tests at `tests/test_soak_promotion_gates.py:439` reproduce `[200, 200, 429]` independently on each replica for the same authenticated and unauthenticated identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` explicitly documents process-local scope. This is not proof of a cluster-wide principal budget; full concurrent security/degraded behavior remains unverified. |
| Complete telemetry with thresholds | **UNVERIFIED.** Process-group sampler tests exercise actual uv child memory/descriptors, but `run_soak.py:1410` records driver loop lag, not application loop lag. Its dedicated driver database probe is not application pool-wait/query telemetry. Complete production telemetry/threshold coverage has not been demonstrated. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427` signals by elapsed time, without selecting/verifying an active Attempt. Process rejoin and aggregate terminal Run counts do not establish absence of lost/duplicated physical effects. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `run_soak.py:730` always returns `ok=False` for artifact identity. Three passing `test_four_hour_preflight_cannot_pass_cli` cases confirm absent/null/preflight identity is rejected even with otherwise passing four-hour evidence. No exact-RC soak was run. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** This report records current limitations locally; no GitHub mutations are permitted. Existing prior reports are not independent proof of complete disposition. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for the RC.** This human report identifies the checked commit and commands but produces no new machine-readable production soak, image digest or exact configuration observation. Old evidence is not transferred to this head. |

ADR-085 was also read: it requires principal-keyed rate limiting, but does not
establish a distributed budget implementation. The issue's stronger
replica-selection criterion is kept unmet, not silently rewritten to local
429 observations. No authorization or limiter authority is replaced here.

## Handoff / residual risks

**BLOCKED for issue acceptance, not a reproducible Vulture or schema-test repair.**
Only this report changed in this round. Preserve all inherited work. Do not
repeat the stale schema mismatch repair or invent scanner debt to justify a
ledger edit. Do not run the host emulator for four hours and label it an RC soak.

Next work needs a selected immutable RC image/configuration and a production
Compose runner/workload exercising the missing supported surfaces, physical
Attempt/effect reconciliation and application telemetry. Resolve the effective
replica-selection budget contract without a competing authorization path; then
execute the complete long soak, review failures, and publish hash-bound machine
and human evidence. No promotion approval is implied by these passing tests.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
0 fresh deterministic validation failures; next: exact-RC production evidence
and the unresolved non-bypass/physical-work checks. Local commit follows.
