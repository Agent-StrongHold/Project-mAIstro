# Issue #860 — job c7ec31fe repair checkpoint

## Frozen scope

Assigned issue #860 only, worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting head `3480cc53a7360ae51e109e241092de8d9684adb4`,
develop base `1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4` (locally resolved).
Initial tree clean; no incoming work needs salvage. Inspect existing soak
profile/evidence/runner/tests, adjacent task/learning-store/rate-limit code,
production Compose, relevant ADRs, and the exact vulture gate. Write only this
checkpoint unless executed evidence establishes a repairable defect in scope.
No RC artifact/configuration manifest supplied: do not invent one or substitute
a host emulator for the promoted deployment. This is a writer repair lane.

Job directory snapshot contains no `check-*.log` files. The prior result and
handoff were read but are not fresh verification. No sync conflict exists.

## Recorded results

- Exact requested command, executed with 1200-second timeout:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  **PASS**, 1355 reviewed identities / 1355 findings, zero unclassified.
  No ledger amendment or dead-code removal is supported by this result.
- Current evidence/profile already correct the old shared-limiter claim and
  explicitly reject host-emulator promotion. No cosmetic correction needed.
- Read repository instructions, ADR-081 (Proposed), accepted ADR-085,
  ADR-081626-f383 and ADR-082426-82c7. Per-principal rate keys do not establish
  shared cluster budgets; occurrence admission does not prove physical-work
  uniqueness. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; do not
  add execution or authorization authority to manufacture acceptance.

## Focused validation

Executed with 1200-second timeouts:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2836 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped**. Skips require `MAISTRO_TEST_PG_DSN`; no live
  PostgreSQL concurrency proof is claimed. The real middleware regressions
  reproduce independent allowances for both authenticated and unauthenticated
  identities; the live-child sampler regression passes.
- `uv run python scripts/check-suite-inventory.py`: PASS, 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 tracked files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Inline `uv run python` imported the current runner and evaluated the frozen
  four historical packs: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`. Assertions that all fail
  both `sustain_duration` and `exact_rc_artifact` passed. Round 5 reports 90.17
  seconds; round 6 reports 90.43 seconds. Also asserted the current preflight
  artifact check returns `ok=false`. This is re-evaluation, not new load.

Inspected production Compose, middleware, the artifact evaluator and adjacent
regressions. Compose declares two applications but requires an external model
provider and pg17, unlike historical provider-less pg18 preflight. Accepted
ADR-082526-b36a adds renewal/reclaim to the lease contract; inspection of that
contract is not live recovery proof. No runtime/configuration, historical
artifact, test or ledger edits made. Inventory delta is zero.

## Acceptance accounting

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC profile | PARTIAL: inspected mix and thresholds; multiple users/Workspaces, fan-out, successful tools/models, Design/Canvas and background workers remain UNVERIFIED. |
| Two deployed application replicas | Compose and boot-contract tests confirm declaration only; live exact-RC replicas UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | UNVERIFIED; historical 90.43-second round 6 is below 14400 seconds. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED; admission-oracle tests are not physical-effect correlation under multi-replica load. |
| Rate/security/degraded non-bypass | UNMET for shared allowance: middleware tests reproduce extra allowance on replica 2. Full production security/degraded coverage UNVERIFIED. |
| Complete production metrics and explicit thresholds | PARTIAL: sampler tests pass; application-loop lag, detached workers and complete production observations UNVERIFIED. |
| Active-work restart, drain, fencing and recovery | UNVERIFIED; no live load run in this round. |
| Long-running exact RC artifact/configuration soak | UNMET: all four packs fail current duration/artifact gates. Immutable RC manifest not supplied. |
| Findings filed/reclassified before promotion | Local F-series classifications inspected; external filing UNVERIFIED and GitHub mutations prohibited. No new load findings. |
| Hash-bound human/machine RC evidence | Historical packs inspected, but qualifying RC evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not merge-ready. No exact-debt repair was needed at this head.
The previous blocker cannot be resolved by static checks or a longer run of the
host emulator. Release-owner input is needed to select the immutable RC
image/configuration/provider deployment; then complete representative workloads,
metrics and physical-effect correlation, resolve replica-selection rate-budget
semantics at the canonical policy seam, and run at least 14400 seconds on the
exact artifact. Re-soak after any code/runtime-config change.

Only this file changed. Commit locally, no push. Progress: checked 1 issue,
acceptance-complete 0, skipped items 0, command errors 0, blocked 1. Stop this
unchanged CI-repair loop until those prerequisites change; another note cannot
supply missing release evidence.
