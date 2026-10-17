# Issue #860 — b11a00ff repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `b9b794a8f24631287141640301292cc2eb4aa09e`, assigned develop base
  `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Initial worktree clean; no salvage patch required.
- Evidence inputs: supplied dispatch-context.json, prior result
  `741717ee76d74bc9b04904598b6dfc90/result.json`, cited prior
  `98a11313167b41a98a420abfda80c292/check-3.log`.
- Current job directory contains no driver `check-*.log` files.
- Review surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/m3a-soak-evidence.md`, production rate-limit middleware,
  related accepted ADRs and quality-gate configuration.
- Conditional repair surface: `quality/vulture-baseline.json` and only source
  identities actually reported by the prescribed scanner. No speculative edits.
- Output surface: this checkpoint. Add inventory notes only if tests change.

Assumption: this is a writer CI-repair round, not a request to approve promotion.
Previous BLOCKED claims require fresh checks; a passing scanner cannot establish
production multi-replica soak acceptance. No GitHub mutations or new execution
authority are permitted.

## Validation

Fresh prescribed Vulture scan passed: 1323 reviewed identities / 1323 findings,
zero unclassified or never-allowlist findings. No ledger amendment warranted.
Fresh schema suite passed: 37 passed, 6 skipped in 1.41 s. The supplied prior
24-versus-21 DDL assertion failure does not reproduce. Logs are `check-vulture.log`
and `check-schema.log` in the assigned job directory (1200-second timeout).
Skipped integration tests are not evidence of production concurrency.

Fresh focused validation (1200-second timeout):

- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  81 passed in 2.38 s (`check-focused.log`).
- `uv run ruff check .`: passed (`check-ruff.log`).
- `uv run ruff format --check .`: 3277 files already formatted (`check-format.log`).

- `uv run python scripts/check-doc-links.py`: passed, 2694 Markdown files,
  zero broken relative links (`check-doc-links.log`).
- `git diff --check`: passed.

No tests changed; no inventory delta is needed. No code/ledger repair is supported
by the reproduced checks. The production middleware test confirms independent
per-replica allowances rather than demonstrating cluster-wide non-bypass.

## Architecture and acceptance assessment

Read repository instructions, documentation authority map, accepted ADR-062
(including the retired entrypoint warning), ADR-082826-b601 and ADR-085.
Execution remains `Goal -> Graph -> Run -> NodeRun -> Attempt`; schedule
admission is not physical execution proof. No new scheduler, authorization path,
or runtime authority is introduced. ADR-085 establishes principal-keyed rate
limits, not a shared cluster allowance. The issue's stronger replica-selection
criterion is unresolved, not waived by the documented process-local behavior.

Acceptance assessed against the issue body in the frozen dispatch snapshot:

| Criterion | Evidence / disposition |
| --- | --- |
| Representative users/Workspaces, mix, Graph fan-out, schedules, tools/models, Design/Canvas, workers | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md:171` explicitly lists missing representative workloads. No complete RC profile was executed. |
| At least two supported production replicas | **UNVERIFIED**. Executed ASGI middleware and boot-contract regressions, not two deployed RC application processes. Historical provisional reports are not fresh acceptance proof. |
| Sustained saturation, queue growth, reclaim, retries, memory/fd/process leaks and restarts | **UNVERIFIED**. Sampler tests observe real child-process resources but not sustained production workloads. |
| No duplicate physical schedule/task/Run/Attempt work or Goal reconciliation | **UNVERIFIED**. Receipt/admission checks do not establish physical execution fencing. Profile phase 4 cancels its probe Run rather than executing it. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**, with contrary evidence for a shared allowance. Executed `tests/test_soak_promotion_gates.py:439`: identical identity receives 200/200/429 separately from each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents N-times aggregate allowance. |
| Complete production metrics with thresholds | **UNVERIFIED**. Sampler/accounting tests passed, but no full production time series; driver-loop lag is not application-loop lag and the profile identifies missing pool/worker/reclaim observations. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup regression is not live active-work recovery or physical-work deduplication. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**. `scripts/soak/run_soak.py:744` always rejects its host-process topology. Executed CLI regressions confirm four-hour preflight evidence still fails. Assignment supplies a source commit, not a designated immutable promoted image/configuration. |
| Load findings filed/reclassified before promotion | **UNVERIFIED**. Historical local findings exist in `m3a-soak-evidence.md`, explicitly provisional; no fresh live-load findings or remote reclassification performed (GitHub mutations prohibited). |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**. This source-validation report and job logs are not hash-tied production-soak evidence. |

## Handoff

**BLOCKED** on production release acceptance. The cited CI failure is stale at
this HEAD; there is no current unbanked Vulture identity to amend. Changing tests,
ledger entries or promotion gates solely to create a repair would be unjustified.
Only this report changes; existing implementation/evidence is preserved.

Next: designate immutable RC image/configuration, complete the representative
production workload and telemetry, resolve the replica-selection contract, then
execute the >=4-hour exact-RC soak with active-work recovery and physical-work
fencing evidence. No repeated passing scanner run can satisfy these prerequisites.

Progress: checked 1 issue; done 0; skipped 0; validation errors 0; next is the
production-soak prerequisite handoff above. Local commit is not integration
approval.
