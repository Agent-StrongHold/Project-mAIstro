# Issue #860 — bounded repair, job 1d1836ea

## Frozen scope

Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `0e9370956e12e93c1acba7902dfad49b1ae3dc65`,
dispatch base `6371967a84626e8aa002fd0af636053853792fc9`.
Initial worktree was clean. No develop-sync conflict is present.

Review inputs are the supplied dispatch-context.json, prior result d97abc74,
and historical check-3.log from job 98a11313. No check-*.log files were present
in this job directory at initial inspection. No remote enumeration or mutation.

Repair targets are the historical schema-fence failure and exact vulture gate;
inspect `pg_learnings.py`, its persistence tests, the soak runner/promotion tests,
rate-limit production code/tests, quality gate implementation/workflow/ledger,
and relevant ADRs/profile/evidence. Change production/tests/ledger only for a
reproduced finding; otherwise record fresh evidence here. No competing execution
or authorization authority will be introduced.

Ambiguity: the provided base is newer than the lane's history in several unrelated
areas. This is not evidence of a merge conflict and does not authorize unrelated
repairs. Preserve the supplied branch. Acceptance requires real exact-RC load,
not passing preflight tests. Prior BLOCKED claims will be checked independently.

## Validation

Fresh exact CI vulture scan passed: 1332 reviewed identities / 1332 findings,
zero unclassified and zero forbidden. No ledger amendment is justified by this
scan; there are no unbanked identities to retain or demonstrated dead identities
to remove. Workflow invocation verified at `.github/workflows/quality.yml:1013`.

Fresh schema module: 37 passed, 6 skipped. Current test lines 175–177 include
all three Gauntlet audit columns; the historical 24-versus-21 failure does not
reproduce. Production `ensure_schema` takes the transaction advisory lock before
DDL. Skipped integration cases do not establish live PostgreSQL behavior.

Fresh focused soak/boot/gitleaks/backpressure tests: 82 passed. Existing profile
explicitly identifies the runner as preflight, not exact Compose RC evidence;
no production or test edit is justified by these passing regressions.

## Executed validation

All validation used 1200-second command timeouts in the assigned worktree.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1332/1332, zero unclassified/forbidden |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 82 passed |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 22 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3105 files |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 28182 unique identities, zero duplicates |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `uv run python -` importing the current soak evaluator and reading `evidence/m3a-round6-shakedown.json` | PASS after correcting this reviewer's JSON lookup: asserted duration/artifact gates fail and current preflight artifact check is false. Observed duration 90.43s versus 14400s minimum. Initial diagnostic incorrectly accessed `summary` instead of `thresholds` and raised `KeyError`; no repository defect or edit resulted. |

## Architecture reconciliation

Read accepted ADR-081226-69ee (canonical Graph/Run/NodeRun/Attempt),
ADR-081626-f383 (Run-store-owned leases/fences; no implicit expiry takeover),
and ADR-085 (principal-keyed rate limits). Issue wording does not authorize
new reclaim, scheduling or authorization authorities. The production middleware
uses the canonical principal resolver but stores counters locally; passing local
limiter tests cannot prove a cluster-wide principal budget. No authority changed.

## Acceptance review

| # | Criterion | Fresh evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC profile | UNVERIFIED. `m3a-load-profile.md:153-172` explicitly lists missing concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and background reconciliation. No immutable RC configuration selected in this round. |
| 2 | At least two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26-78` defines two services, but executed ASGI tests are not a live deployment. |
| 3 | Sustained saturation, reclaim, retry and leak observations | UNVERIFIED. Evaluator executed on preserved evidence rejects 90.43s versus 14400s; no new production soak ran. Reclaim must follow accepted authority contracts. |
| 4 | No duplicated physical work, including schedules/tasks/Runs/Attempts/Goals | UNVERIFIED. `m3a-load-profile.md:195-204` says the occurrence probe cancels its queued Run without executing it. Admission and backpressure tests do not prove physical-work deduplication. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: executed `tests/test_soak_promotion_gates.py:439-488` observes `[200,200,429]` independently on each replica for the same identity. Production limiter constructed at `api/rate_limit.py:72` is registered at `maistro_server/main.py:648`. Local enforcement passed; sustained security/degraded behavior remains UNVERIFIED. |
| 6 | Complete telemetry and explicit thresholds | UNVERIFIED. Profile documents driver rather than application loop lag and incomplete worker/pool/reclaim/leak observations. Threshold and accounting unit tests do not supply production telemetry. |
| 7 | Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Boot/cleanup tests passed, but no live active-Attempt recovery experiment ran. |
| 8 | Long-running exact RC artifact/configuration soak | NOT MET by evaluated evidence: `sustain_duration` and `exact_rc_artifact` fail. Current `scripts/soak/run_soak.py:730-741` deliberately rejects host preflight as production artifact proof regardless of duration. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. Backlog consistency passing does not prove filing completeness. GitHub mutations prohibited and not attempted. |
| 10 | Machine/human soak evidence bound to image/package/commit/config hashes | UNVERIFIED for production. Existing preflight artifacts preserved. This report is validation evidence, not a production soak attestation. |

## Handoff

**BLOCKED** on production acceptance, not a reproduced schema or vulture CI
failure. Changed file: only this report. No tests added, so no inventory-delta
note is required. No ledger/grant, runtime, test or gate changes are warranted
by the executed checks. No work discarded, remote mutated, or push attempted.

Next: release owner must select the exact immutable RC image/configuration and
representative workload applicability; reconcile aggregate rate-budget semantics;
then implement/run a production-topology soak with physical-work/recovery oracles
and complete telemetry for at least four hours. Another short preflight or stale
schema-failure redispatch cannot establish acceptance. Existing evidence is not
invalidated or promoted by this documentation-only commit.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC acceptance
prerequisites}. The one diagnostic error was corrected above; validation handoff
is complete, issue acceptance is not.
