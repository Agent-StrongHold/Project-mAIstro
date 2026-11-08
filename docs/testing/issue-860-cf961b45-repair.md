# Issue #860 — cf961b45 repair checkpoint

## Frozen scope

- One item: issue #860, branch `auto-860`, starting commit
  `048789cc6dac9a1338750974e136160bf298a913`, assigned base
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Worktree was clean. No salvage required.
- Inputs: supplied dispatch-context.json, prior result 44a74ef6, prior
  check-3.log from 98a11313, repository instructions, soak implementation/tests,
  relevant execution ADRs, exact vulture checker/workflow and baseline.
- Planned edits: this report; quality/vulture-baseline.json only if the exact
  scan demonstrates reviewed retained debt; implicated production code/tests
  only if an actual dead-code defect is demonstrated. No unrelated repairs.
- Current job directory contains no driver check-*.log files.

## Assumption and limits

This is the writer CI-repair lane, not permission to declare an unrun exact-RC
soak successful. The prior BLOCKED verdict is evidence to investigate, not an
acceptance result to trust. No alternate scheduler/authorization path will be
introduced. No remote mutations.

## Progress

Exact vulture gate passed: 1323 reviewed identities / 1323 findings, zero
unclassified and never-allowlist findings. No ledger amendment is justified.
The supplied historical check-3.log instead reports the learning-schema test's
21-versus-24 DDL assertion. Fresh focused execution passed: 130 passed, 6
skipped in 3.08 seconds, including that regression, soak promotion gates,
backpressure, execution fencing and recovery disposition. `uv sync --locked
--extra dev` passed. Skipped tests do not establish live PostgreSQL coverage.
Architecture and static validation completed below. No production code, tests,
inventory or quality ledger changed; this report is the only changed file.
No test additions means no inventory delta is needed.

## Commands and outcomes

Validation commands used 1200-second timeouts:

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323 identities; matches `.github/workflows/quality.yml:1078`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: PASS, 130 passed / 6 skipped in 3.08 s.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3277 files).
- `uv run python scripts/check-deployment-claims.py`: PASS; static component existence, not deployed behavior.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified / 19 discovered.

The historical schema failure is already addressed in the starting tree:
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177` includes
the three Gauntlet audit columns in the independent expected DDL list.
Production `pg_learnings.py:215` encloses the upgrades in a transaction with
an advisory lock. No weakened assertion or guessed scanner amendment was made.

## Architecture reconciliation

Read repository AGENTS.md and accepted ADR-081626-f383, ADR-085,
ADR-082526-b36a and ADR-082826-08f0. Later renewal/recovery decisions extend
the original lease contract: live leased work refuses recovery; expired work
reclaims through the canonical lifecycle seam. Admission uniqueness alone does
not prove physical execution uniqueness. Preserve Goal -> Graph -> Run ->
NodeRun -> Attempt, canonical identity and event authority. No alternate
scheduler or authorization mechanism is introduced.

## Acceptance checked against reachable behavior

| Criterion | Fresh evidence and disposition |
| --- | --- |
| Representative release-candidate profile | UNVERIFIED. Read `docs/testing/soak/m3a-load-profile.md`: explicitly missing users/Workspaces, graph fan-out, successful model/tool work, Design/Canvas and Goal/background activity. Selected-RC applicability is not established. |
| At least two deployed application replicas | UNVERIFIED. Executed middleware instances are ASGI fixtures, not deployed promoted images. |
| Sustained saturation, queues, reclaim, retry/backoff, leaks and shutdown | UNVERIFIED. Focused tests took seconds, not a sustained observation window. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | UNVERIFIED under load. Bounded canonical fencing/recovery tests pass; neither admission IDs nor a cancelled schedule probe establish this deployed claim. |
| Non-bypassable rate limiting, security and degraded behavior | NOT SATISFIED at the middleware seam: freshly executed `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]` independently on both instances for the same authenticated/unauthenticated identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates a local limiter; `main.py:648` installs it in production. Full deployed security/degradation remains UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED. No fresh production query/lock, application-loop, worker/RSS/descriptor/queue/error/timeout time series. Driver-loop sampling is not application-loop sampling. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED under sustained deployed traffic; bounded canonical recovery tests pass. |
| Long exact-RC soak, rerun on artifact/config changes | UNVERIFIED. `scripts/soak/run_soak.py:744` returns `exact_rc_artifact.ok=false`; freshly executed CLI regression at `tests/test_soak_promotion_gates.py:103` rejects synthetic four-hour host-preflight evidence. No immutable promoted artifact/configuration was designated in the lane assignment. |
| Findings classified to earliest broken invariant | Existing cluster-budget gap is tracked at `BACKLOG.md:267` (engine-116); completeness UNVERIFIED without a sustained investigation. No GitHub mutations. |
| Human/machine evidence bound to image/package/commit/config hashes | UNVERIFIED. This source-head report is not an exact-RC production evidence pack. |

## Disposition and next prerequisite

**BLOCKED** for #860 acceptance. The requested CI failure did not reproduce;
there is no evidence-supported ledger repair. The prior blocker is not a
merge conflict and remains unresolved. Another identical CI-repair dispatch
cannot produce production-soak proof.

Next requires a designated immutable RC image/configuration, the cluster-wide
budget prerequisite through the existing limiter/identity seam, a representative
production-path workload, and at least four hours of exact-RC telemetry with
active-work failure/recovery and physical-work uniqueness evidence. A longer
host preflight cannot substitute. Do not weaken promotion gates or reinterpret
passing tests of known limitations as acceptance.

Progress: checked 1, acceptance-complete 0, skipped 0, validation errors 0.
Local documentation commit only; no integration approval or issue closure.
