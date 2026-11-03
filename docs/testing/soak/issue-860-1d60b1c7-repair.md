# Issue #860 — repair validation 1d60b1c7

## Frozen scope

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting clean at `f261a37f9b1fee110b1c72691e76366d3eee7032`;
supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7` resolves.
No PR processing, remote refresh, merge, or GitHub mutation.

Inspection scope: supplied dispatch-context.json, historical check-3.log and
58cc75a7 result/report; repository instructions; ADR-081226-69ee,
ADR-081626-f383, ADR-082526-b36a, ADR-085 and proposed ADR-081;
`scripts/soak/run_soak.py`, `docs/testing/soak/m3a-load-profile.md`,
`tests/test_soak_promotion_gates.py`, production rate-limit middleware/main,
production PgLearningStore/schema-fence tests and task-backpressure tests.
Edit scope: this report, and the vulture ledger only if the required scan
identifies actual discrepancies. No test additions planned.

Ambiguity resolved: this is the writer repair lane, not the verifier lane.
CI repair and full release acceptance are distinct. The prior BLOCKED result
concerns absent exact-RC soak evidence, not a merge conflict; no sync needed.
The supplied current job directory contains no check-*.log files.

## Fresh results

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings / 1323 reviewed identities, zero unclassified or never-allowlist. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS, 37 passed, 6 skipped. The historical check-3.log failure (24 schema statements versus 21 expected) does not reproduce. Skipped database tests are not live concurrency proof.

## Architecture reconciliation

Accepted Graph/Node and lease ADRs retain canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority. The later renewal/reclaim
ADR extends the earlier fencing boundary; its acceptance is not waived by the
earlier deferral. ADR-085 specifies per-principal keying, not an implemented
cluster-wide limiter. Proposed ADR-081 cannot override accepted execution
contracts. No runtime, scheduler, authorization, or event authority changed.

## Additional executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 66 tests.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 31128 unique identities, no duplicate evidence.
- `git diff --check`: PASS.
- A final diagnostic grep for `async with conn.transaction` returned 1 (no literal match), making the combined shell command exit 1 after the successful validations. Reading `pg_learnings.py:215` confirmed the combined acquire/transaction context; this was not a test failure.

Current schema test expectations at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`
include all three validation-audit columns missing from the historical failure.
Production `pg_learnings.py:215` acquires the transaction before the advisory
lock and all upgrade DDL. No change is justified by the stale failure.

Production `maistro_server/main.py:648` installs `RateLimitMiddleware`.
`maistro_server/api/rate_limit.py:93` constructs an instance-local limiter.
Executed `tests/test_soak_promotion_gates.py:439` sends the same identity to
two actual middleware instances: each independently returns 200, 200, 429.
This reproduces local rather than cluster-wide enforcement. These are ASGI
tests, not a deployed concurrency soak; the documented N-times-limit semantics
cannot establish the issue's stronger replica-selection non-bypass criterion.

## Acceptance assessment

| Criterion | Executed evidence or explicit gap |
| --- | --- |
| Representative RC profile | UNVERIFIED. Reviewed `m3a-load-profile.md:155`: concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal/background workloads remain missing; selected RC scope not supplied. |
| At least two deployed replicas | UNVERIFIED. Tests use two middleware instances, not deployed RC services. |
| Sustained saturation, queues, reclaim, retries and leaks | UNVERIFIED. Unit/probe tests are not a sustained observation window. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | UNVERIFIED. Tests reject empty/conflict-only admission evidence but do not witness physical execution across deployed replicas. |
| Rate/security/degraded non-bypass | UNVERIFIED at deployment grade; independent allowances reproduced by the production-middleware test. Backpressure test proves canonical task admission returns retryable 429 and admits again after a slot frees, not complete security/replica non-bypass. |
| Full telemetry and explicit thresholds | UNVERIFIED. Profile explicitly lacks application-loop, pool-saturation and worker/reclaim observations; driver-loop lag is not application-loop lag. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. Gate tests pass; no active RC replica restarted here. |
| Long soak of exact RC artifact/configuration | UNVERIFIED / BLOCKED. `scripts/soak/run_soak.py:730` always rejects host-process preflight as exact-RC evidence. Executed four-hour synthetic gate tests prove rejection, not a four-hour soak. No designated immutable RC/configuration supplied. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external reclassification UNVERIFIED. No GitHub mutations permitted or performed. |
| Hash-bound machine/human evidence | UNVERIFIED for this RC. Historical preflight artifacts and this report cannot certify the current release artifact. |

## Handoff

Only this report changed. No source, tests, inventory counts, grants or ledgers
changed; no inventory-delta note required. Existing work preserved.
No reproducible CI failure or unbanked identity was found to repair.

Verdict: **BLOCKED**, not MERGE-READY. Required next inputs/work are a designated
immutable RC artifact/configuration and representative workload scope, an
exact-topology runner with complete telemetry/physical-work witnesses, and a
fresh minimum-four-hour soak with active-work recovery. Repeating passing
CI-repair scans cannot resolve that release prerequisite. Do not weaken the
preflight artifact gate or relabel ASGI tests as release evidence.

Progress: checked 1 issue; done 0 (acceptance incomplete); skipped 0;
validation failures 0; diagnostic no-match 1. Report committed locally for
handoff only; no integration approval.
