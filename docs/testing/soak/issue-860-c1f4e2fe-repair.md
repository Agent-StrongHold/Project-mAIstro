# #860 bounded CI-repair handoff — c1f4e2fe

## Scope and disposition

Assigned worktree `auto-860`, clean starting HEAD
`3e9c3ff65161b54156707f492af1baed71253c00`; supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Only #860 was processed.
Read repository instructions, supplied dispatch issue/most recent comments,
prior result and cited historical failure. This job directory contained no
`check-*.log` files. No conflict exists; no merge or GitHub mutation performed.

**BLOCKED: no evidence-backed CI repair remains in the supplied failure.**
Do not repeatedly dispatch that stale failure as a current scanner defect.
The exact vulture scan passes without a ledger amendment. The historical
`98a11313.../check-3.log` failure expected 21 DDL statements but observed 24;
the current test already independently expects all 24, including the three
Gauntlet audit columns at `test_pg_learnings.py:173–178`. Fresh execution passes.
No production, tests, ledgers, grants, or configuration changed this round;
only this handoff is added. Inventory delta is zero.

## Fresh validation (1200-second timeouts)

| Executed command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities / 1323 findings; zero unclassified; gate-selected base `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; not live database evidence |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3270 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run python scripts/check-suite-inventory.py` | 17 suites match; 31128 unique identities; zero duplicate evidence |

Vulture arguments match `.github/workflows/quality.yml:1078` and
`vulture-ratchet.yml:82`. Passing checks do not establish release acceptance.

## Acceptance checked against reachable behavior

| #860 criterion | Evidence and remaining disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:155` lists omitted users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/worker workloads. Applicability requires designated RC configuration. |
| Two application replicas | UNVERIFIED for deployed RC: executed two production-middleware ASGI instances, not deployed images. |
| Sustained saturation, queues, lease reclaim, retry, leaks | UNVERIFIED: sampler/gate tests passed, but no sustained RC traffic executed. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED: admission receipts and terminal state are not physical-work witnesses; schedule probe cancels its Run without execution (profile:206–210). |
| Rate/security/degraded non-bypass | UNVERIFIED at deployment grade; executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) reproduces two accepted requests on each replica for one exhausted identity. The backpressure router test proves 202/429/Retry-After and resumed admission, not crash recovery. |
| Full telemetry with thresholds | UNVERIFIED: profile documents missing application event-loop/worker observations; driver loop lag is not application loop lag. No new RC metrics captured. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: boot-cleanup unit tests are not deployed active-work recovery. |
| Long exact-RC soak | BLOCKED / UNVERIFIED: no designated immutable RC artifact/configuration supplied. `scripts/soak/run_soak.py:730` rejects host preflight as artifact proof; executed synthetic four-hour CLI tests confirm fail-closed behavior, not four hours of load. |
| Findings disposition | Local rate-policy/evidence gaps documented here and in existing profile; external filing/reclassification UNVERIFIED (GitHub mutations prohibited). |
| Machine/human evidence bound to RC hashes | UNVERIFIED: this report identifies validated source HEAD; it is not a hash-bound deployed soak artifact. |

## Architecture reconciliation and next action

Read accepted ADR-081226-69ee (Graph execution), ADR-081626-f383 (fencing),
ADR-082526-b36a (renewal/reclaim), and ADR-085 (rate policy). Renewal/reclaim
extends the older fencing boundary; the old deferral does not waive validation.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and existing authorities.
Production `main.py:648` installs `RateLimitMiddleware`; its constructor
(`api/rate_limit.py:93`) creates local state. The documented N-times aggregate
allowance is not proof of the stronger #860 replica-selection non-bypass claim.
No speculative distributed limiter or alternate authorization path was added.

Next: designate immutable RC images/configuration and workload applicability;
resolve the rate-policy acceptance discrepancy; execute the exact topology with
physical-work/fencing witnesses, complete telemetry, active-work recovery and
at least four sustained hours. A longer host preflight cannot substitute.

Progress: checked 1, done 0 (acceptance incomplete), skipped 0, validation errors 0.
Local commit is a handoff, not integration approval. Existing branch work preserved.
