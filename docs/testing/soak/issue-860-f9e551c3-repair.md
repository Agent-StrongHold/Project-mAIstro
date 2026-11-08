# Issue #860 CI-repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `eff82f23c076f6c133ffd39ecb8acf4ca236163b`, supplied base
  `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Starting worktree clean; no incoming changes to salvage.
- Files in repair scope: this report, `quality/vulture-baseline.json` only for
  scanner-confirmed reviewed retained identities, and the source identities
  reported by the prescribed vulture command if genuinely dead. Existing soak
  scripts/tests/docs are inspection and validation inputs, not a new feature scope.
- No remote operations. No production artifact/configuration is supplied in the
  assignment; do not substitute component tests for the requested RC soak.
- Current job directory contains no `check-*.log` files. Prior result reports
  BLOCKED; this is a claim to revalidate, not acceptance evidence.

## Progress

Snapshot and clean starting head verified. Read supplied issue acceptance and
prior result. Prescribed Vulture scan passed: 1323 reviewed identities / 1323
findings, zero unclassified or never-allowlist. No ledger amendment justified.
Prior check-3.log contains a 24-versus-21 schema DDL assertion failure; focused
reproduction passed on the assigned head (see commands below). Current source rejects host-process preflight as exact-RC
evidence (`scripts/soak/run_soak.py:744`). The profile explicitly documents
missing representative workloads and physical-work recovery coverage. These
are acceptance blockers, not scanner defects.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, accepted ADR-082826-b601
(canonical Run consumer) and ADR-085 (principal-keyed limits). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no replacement scheduler, store,
authority or authorization path is warranted. Admission uniqueness is not proof
of physical-work fencing. ADR-085 does not provide evidence of a shared replica
budget; no acceptance waiver is inferred from the current process-local limits.

The production application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates
an `InMemoryRateLimiter` at `api/rate_limit.py:94`. The executed production-
middleware regression at `tests/test_soak_promotion_gates.py:439` demonstrates
independent 200/200/429 allowances for the same identity on two instances, for
both authenticated and unauthenticated requests. This contradicts treating local
429 responses on all routes as proof of replica-selection non-bypass.

The historical DDL failure is already addressed: the independent expectation at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:161` includes all
24 statements, including three validation audit columns. Production acquires
the transaction advisory lock before its DDL at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.

## Fresh validation

Commands executed locally with 1200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1323/1323 identities, no unbanked findings.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3277 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  — PASS, 118 passed / 6 skipped in 2.54 seconds. Skipped database tests are not
  production evidence. The historical check-3 failure does not reproduce.
- `uv run python scripts/check-doc-links.py` — PASS, 2701 Markdown files,
  zero broken relative links.
- `git diff --check` — PASS.

## Acceptance disposition

| Issue criterion | Fresh evidence / unresolved requirement |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: profile lines 171 onward explicitly omit concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and reconciliation. |
| Two production application replicas | **UNVERIFIED**: executed ASGI/boot tests, not an exact-RC deployment. |
| Sustained saturation, queue growth, reclaim/retry and leaks | **UNVERIFIED**: no long-running production experiment executed. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**: profile describes one admission race followed by cancellation without physical execution; component admission tests cannot establish this. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED** at deployment scale; executed middleware test demonstrates independent allowances, as detailed above. |
| Complete telemetry with thresholds | **UNVERIFIED**: profile distinguishes driver-loop from application-loop latency and documents missing saturation/reclaim and long-window observations. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**: no live recovery run; process rejoin alone cannot establish work safety. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**: no designated immutable RC supplied; runner explicitly fails exact-RC gate at line 744. A longer host-process run cannot fix artifact mismatch. |
| Findings filed/reclassified before promotion | **UNVERIFIED**: no new live-load finding or remote filing; remote mutation prohibited. Blockers recorded locally. |
| Machine/human hash-bound production evidence | **UNVERIFIED**: this report is bound to source HEAD, not a production image/configuration soak. |

## Handoff

**BLOCKED**. No scanner defect or reproduced schema failure justifies a source or
ledger edit. Only this report changes; no tests added/changed, hence no inventory
delta. No merge conflicts observed; no fetch/merge or remote mutation performed.
All existing work preserved. This local report commit is not integration approval.

Next: designate an immutable RC image/configuration and production-soak owner,
complete representative workloads/telemetry, resolve the replica-budget invariant,
then run the >=4-hour exact-RC profile including physical-work fencing and
active-work recovery. Repeating this CI-only repair cannot satisfy those missing
criteria; a new CI-repair dispatch should carry a fresh failing command.

Progress: checked 1, done 0 acceptance-complete issues, skipped 0, validation
errors 0; next is the production-soak handoff above.
