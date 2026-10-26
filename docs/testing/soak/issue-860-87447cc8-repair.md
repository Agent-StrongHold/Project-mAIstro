# Issue #860 — repair checkpoint (87447cc8)

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `12cebed398240614f7a0c0635b71b9365fab5bc3` (clean).
- Supplied base: `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Inspect the supplied dispatch snapshot, prior result and named failed log;
  production soak runner, its adjacent tests, production rate-limit wiring,
  relevant ADRs, CI vulture gate and existing ledger.
- Candidate edits: this report; only evidence-backed fixes in that scope and
  inventory notes if tests change. No GitHub mutations or integration actions.
- Current-job check logs: not supplied (initial directory snapshot contains none).
- Prior result reports BLOCKED, not a sync conflict. Treat all prior pass claims
  as unverified pending fresh commands. No develop merge is indicated.

## Progress

Requested exact Vulture gate executed successfully: 1323 findings, 1323
reviewed identities, zero unclassified, zero never-allowlist. No ledger repair
is justified by the fresh scan. The gate resolved baseline `3c761d14db94`.
The historical failed log is instead a schema-test mismatch (24 statements
versus 21 expected). Its current regression will be rerun.

Ambiguity: mixed verifier/writer wording is resolved as writer mode by the
explicit repair assignment and mandatory commit. Prior BLOCKED is an acceptance
block, not evidence of a develop sync conflict.

## Executed validation

All commands exited 0 (1000–1200 second timeouts):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: 1323/1323 identities, no unbanked debt.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: **118 passed, 6 skipped**, 2.80 seconds. Skips are not live-database evidence.
- `uv run python scripts/check-doc-links.py`: 2698 markdown files, zero broken relative links.

The historical schema mismatch no longer reproduces. The current test explicitly
includes the three audit columns at `test_pg_learnings.py:175`; production takes
its transaction-scoped advisory lock before DDL at `pg_learnings.py:215`.
No source or ledger repair is supported by these results.
A subsequent wiring lookup at `packages/maistro-server/src/maistro_server/app.py`
returned not found; skipped. The executed regression imports the actual
`maistro_server.api.rate_limit` middleware; it does not establish live deployment
wiring. `git diff --check` passed.

## Architecture reconciliation

Read repository instructions, documentation authority map, ADR-062,
ADR-082826-b601 and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The old `run_graph` entrypoint is retired; schedule admission uniqueness is not
proof of physical execution uniqueness. Canonical consumer execution, not a new
scheduler, must supply that evidence. ADR-085's principal-keyed limits do not
establish shared replica budgets. The process-local semantics documented by
production middleware do not waive #860's replica-selection acceptance criterion.

## Acceptance review

| Criterion from supplied issue snapshot | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:171` identifies missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and reconciliation workloads. |
| At least two production replicas | **UNVERIFIED**. ASGI middleware and boot-contract tests are not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED**. No long-window production observations collected. |
| Physical deduplication and Goal reconciliation | **UNVERIFIED**. Admission tests do not establish physical Attempt fencing. The profile's schedule probe cancels its queued Run without executing it. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED** at production scale; contrary shared-budget evidence: executed `tests/test_soak_promotion_gates.py:439` receives 200/200/429 independently from both production middleware instances for the same authenticated or anonymous identity. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Partial thresholds exist, but application event-loop latency, saturation/reclaim and long-window observations are absent. Driver-loop latency is not application-loop latency. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. No production active-work recovery exercised. |
| Long-running exact-RC soak | **UNVERIFIED**. `scripts/soak/run_soak.py:744` explicitly rejects host-process topology as exact-RC evidence; passing promotion-gate tests preserve that rejection. No immutable RC image/configuration designated in the assignment. |
| Findings filed/reclassified | **UNVERIFIED**. No new live-load findings collected or remote filing performed; GitHub mutations prohibited. |
| Human/machine evidence tied to exact hashes | **UNVERIFIED**. This is source-validation evidence, not a hash-bound production soak bundle. |

## Handoff

**BLOCKED**, not merge-ready. The requested CI gate and historical schema test
pass, but the previous production acceptance block remains unresolved. Only this
report changes; no source, tests, ledger, grants, gates or runtime configuration
changes. No new tests means no inventory delta. Existing branch work is preserved.

Next: designate the immutable RC artifact/configuration, complete representative
workloads and telemetry, resolve replica-selection semantics, then execute the
profile's >=4-hour exact-RC soak including physical-work fencing and active-work
recovery. Repeating the CI repair without those prerequisites cannot satisfy #860.
Local commit is a handoff only, not integration approval.

Progress: checked 1, done 0, skipped 0, validation errors 0 (one missing-path
lookup recorded above); next: production soak
prerequisites and owner handoff.

