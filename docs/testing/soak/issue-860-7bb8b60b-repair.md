# Issue #860 — bounded CI repair (7bb8b60b)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `38363dad46c8f976980daf9acb6af146f08a3f2a`; supplied develop base
  `feb19affc965155aede51b1d99825405e67e3786` resolves locally.
- Worktree was clean. No incoming work needed salvage.
- Read-only evidence: supplied dispatch snapshot and prior result/check log,
  repository instructions, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, server rate/admission implementation
  and adjacent tests, existing soak profile/evidence and quality workflow.
- Candidate edits: this report; `quality/vulture-baseline.json` only if the
  prescribed scan identifies reviewed retained identities; production/tests
  only if that scan demonstrates an issue within this lane. No list refresh,
  unrelated develop reconciliation, GitHub mutation, or authority changes.
- No `check-*.log` files were present in the supplied current job directory.
  Execute fresh validation instead of assuming earlier claims.
- The two-tip diff includes unrelated develop evolution. It is not evidence
  of deletions made in this round; do not repair unrelated packages.

## Progress

Initial snapshot complete. The requested vulture gate PASSed: 1,332 reviewed
identities / 1,332 findings; zero unclassified or never-allowlist findings.
The gate selected trusted base `1df433bf5ece` (not the supplied dispatch base).
No evidence supports changing the ledger or removing production code.

The supplied old `98a11313167b41a98a420abfda80c292/check-3.log` is a schema-test
failure (24 DDL statements versus 21), not a vulture failure. Fresh scoped
validation passes that test: 60 passed, 6 PostgreSQL-gated skips across learning
persistence, rate middleware and task-backpressure tests. The soak/boot/ignore
contract tests pass: 81 passed. Dependency sync, repository-wide ruff lint and
format (3,105 files), and suite inventory (17 suites / 28,182 identities, zero
duplicate evidence) all pass. No tests changed, so no inventory delta is needed.

Read accepted ADRs 081226-69ee, 081626-f383, 082526-b36a, 082826-08f0 and 085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; recovery must refuse live
leased work, and admission counts are not physical-execution fencing evidence.
ADR-085 establishes principal identity but does not establish a distributed
rate-limit budget. No new execution or authorization authority is warranted by
this CI repair. The executed test
`test_replica_selection_has_an_independent_production_allowance` demonstrates
that exhausting one real middleware instance does not exhaust another with the
same principal/IP. This is an ASGI seam test, not a deployed production soak.

Current `failed_promotion_checks` evaluated frozen
`evidence/m3a-round30-shakedown.json`: failed gates exactly `sustain_duration`
and `exact_rc_artifact`. Duration is 420.08 seconds against the 14,400-second
minimum. Assertions also verified `preflight_artifact_check()['ok'] is False`.
This re-evaluates historical evidence, not a new load run. No live RC soak has
been executed in this round.

Production reachability checked:

- `packages/maistro-core/src/maistro/container.py:3090` calls learning-store
  schema upgrade. Production audit columns at `pg_learnings.py:118-120` match
  the independent test expectations at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the tested
  middleware. Its constructor at `api/rate_limit.py:69-78` creates an in-memory
  limiter per instance; the scope is explicitly documented at lines 25-30.
- `packages/maistro-server/src/maistro_server/api/tasks.py:117` handles canonical
  `RunConcurrencyExceeded`. The executed adjacent test uses the real router,
  queue and Run spine, but deliberately starts no worker. It proves backpressure,
  not uniqueness of physical execution.
- `scripts/soak/run_soak.py:730-741` disqualifies this host-process driver from
  exact-RC certification; lines 1552 and 1599-1602 wire artifact and duration
  checks into generated evidence.

## Executed commands

All validation commands used 1,200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,332 findings / reviewed identities; arguments match `.github/workflows/quality.yml:1013-1016` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,105 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 60 passed, 6 PostgreSQL-gated skips; no live DB claim |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q` | 81 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28,182 identities |
| `uv run python -` importing the driver and evaluating round-30 evidence | Assertions PASS; historical promotion gates fail duration and artifact |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `git diff --check` | PASS |

## Acceptance disposition

**BLOCKED — clean CI is not production promotion evidence.** The snapshot's
acceptance remains the contract, not the narrower preflight gates.

| #860 criterion | Executed evidence / gap |
| --- | --- |
| Representative users/Workspaces, request mix, Graph/node fan-out, schedules, queues, tool/model, Design/Canvas/background work | **UNVERIFIED.** `m3a-load-profile.md:153-172` identifies missing workload classes. No representative exact-RC workload was executed. |
| At least two production application replicas | **UNVERIFIED live.** Executed tests instantiate two middleware instances; they do not deploy the production replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, resource leaks, restart observations | **UNVERIFIED.** Historical evidence fails the current minimum-duration gate. Sampler tests prove measurement behavior, not sustained production health. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED.** Admission/receipt tests are not physical-work oracles. The profile at lines 195-204 explicitly distinguishes one cancelled schedule-probe Run from sustained Goal reconciliation. |
| Rate/security/degraded behavior effective under concurrency, not bypassable by replica selection | **Not proven.** Executed `tests/test_soak_promotion_gates.py:439-488` demonstrates a second allowance after the same identity exhausts the first. Broader security/degraded production behavior remains **UNVERIFIED**. |
| Complete PostgreSQL/query/lock, application-loop, process/RSS/FD, queue/error/timeout telemetry with thresholds | **UNVERIFIED at promotion grade.** Driver-loop lag does not measure application-loop latency; no new long-window production series captured. |
| Kill/restart during active work; drain/fencing/recovery without loss or duplication | **UNVERIFIED.** No live active-Attempt restart performed. Process exit/rejoin and terminal Run counts alone cannot meet the accepted recovery/fencing ADRs. |
| Long-running exact RC/configuration soak, rerun on runtime changes | **NOT MET by evaluated evidence.** 420.08 < 14,400 seconds; current host-process artifact gate always fails. A longer emulator run cannot close this. |
| Findings filed/reclassified to earliest broken milestone before promotion | **UNVERIFIED for completeness.** Local blockers retained here. Backlog consistency is not proof of complete filing; no GitHub mutations performed. |
| Human/machine evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for the promotion RC.** Historical JSON exists but does not establish the promoted artifact/configuration. |

## Handoff

Only this report changes. No source, tests, inventory notes, ledger/grants,
gates, runtime configuration or historical evidence was modified. The reported
CI failures did not reproduce; speculative ledger edits would not be a repair.
No merge conflict exists in the worktree, so the conditional conflict-repair
instruction does not apply.

Next requires an immutable RC/configuration selection, representative production
runner and physical-work/recovery/telemetry oracles, resolution of the aggregate
rate-limit contract, and then a >=4-hour exact-artifact soak. Do not redispatch
this stale schema failure or passing vulture scan as if it supplies those missing
prerequisites. No acceptance waiver or alternate authority was introduced.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production acceptance prerequisites}.
The bounded CI investigation is complete; issue #860 is not promotion-ready.
