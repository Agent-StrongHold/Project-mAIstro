# Issue #860: round 13 CI repair and acceptance check

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `965f75c14e55e567f2dc95119b0be605d23fb1ff`.
- Assigned base: `e2b2dfa028220a348e9ac934cb8dab2d1761f1cf`.
- Initial worktree clean; no incoming changes to salvage.
- Repair targets: `quality/vulture-baseline.json` (explicitly authorized CI-repair exception), genuinely dead identities reported by the requested vulture gate if any, and this handoff. No production topology or execution-authority changes planned.
- Validation targets: existing soak harness/promotion tests, touched persistence/task tests, replica rate-limiter tests, relevant ADRs and existing load/evidence documents. No new test cases planned.
- Job directory contains no `check-*.log` files at initial inspection; no driver check success is assumed.

## Assumptions and current state

This is a writer/CI-repair assignment. The prior result artifact exists and reports BLOCKED, but its validation claims require fresh checks. No designated promotion RC image/configuration was supplied. Historical host-preflight evidence cannot substitute for an exact-artifact four-hour soak. External issue filing is prohibited by the lane instructions; findings can only be classified locally.

## CI-repair result

Executed the requested exact vulture command with a 1200-second timeout:

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

PASS: 1402 findings matched 1402 reviewed identities; `unclassified: 0`, `never_allowlist: 0`. Log: job directory `vulture-repair.log`. There are no unbanked identities or eliminated identities to amend. Changing the ledger or deleting retained code would not address an actual finding, so neither is justified.

Read accepted ADR-081426-1f7c (Attempt mechanics), ADR-081626-f383 (canonical store owns execution fencing), ADR-085 (per-principal rates), and ADR-083026-a91e (no invented measurements). No execution, scheduling, event or authorization authority is changed. Admission uniqueness must not be reported as proof of unique physical effects.

## Fresh validation

Commands used 1200–1800 second timeouts. Logs are under
`/home/dev/maistro/jobs/e8492921943546769fdd4a2d555f2fa8/`.

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs`
  — **102 passed, 5 skipped in 11.72s** (`writer-pytest.log`). All skips require `MAISTRO_TEST_PG_DSN`; this run provides no live PostgreSQL validation.
- `uv run ruff check .` — PASS (`writer-ruff-check.log`).
- `uv run ruff format --check .` — PASS, 2624 files (`writer-ruff-format.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — PASS, 4198 tests (`writer-inventory.log`). No test additions or edits; inventory delta is zero.
- `uv run python -` — imported the current soak harness and evaluated the preserved round-6 evidence. Assertions passed: 90.43 seconds < 14400 seconds, failed gates exactly `sustain_duration` and `exact_rc_artifact`, current `preflight_artifact_check().ok == False` (`writer-evidence-check.log`). This is evidence evaluation, not a new soak.
- Production wiring inspection: `packages/maistro-server/src/maistro_server/main.py:478` installs the same `RateLimitMiddleware` tested by `tests/test_soak_promotion_gates.py:439`. Its authenticated and unauthenticated parameterizations demonstrate independent `[200, 200, 429]` allowances across two instances. Tests exercise production middleware, not deployed replicas.

## Acceptance disposition

| # | Criterion | Fresh evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC load profile | PARTIAL: inspected `m3a-load-profile.md`; mix and thresholds exist, but its remaining-profile-gaps section explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. RC representativeness UNVERIFIED. |
| 2 | At least two application replicas | Reference `deploy/docker-compose.prod.yml:27-62` defines two application services. Execution of the exact production artifact on two replicas UNVERIFIED. Middleware instances do not satisfy this criterion. |
| 3 | Sustained saturation, queue growth, reclaim, retry, leaks and shutdown | UNVERIFIED: current evaluator rejects historical 90.43-second evidence. No new sustained run executed. |
| 4 | No duplicate physical work across schedules/tasks/Runs/Attempts; Goal reconciliation | UNVERIFIED: admission-oracle regression tests pass, but synthetic receipts and a historical one-occurrence admission race are not physical-effect or sustained reconciliation proof. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority is unchanged. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for one aggregate principal allowance: executed middleware regressions demonstrate an independent allowance on replica 2. `rate_limit.py:25-30` explicitly documents N-times-limit semantics. Full RC security/degraded behavior UNVERIFIED. |
| 6 | Complete metrics and explicit thresholds | PARTIAL: profile has thresholds and sampler tests observe real child-process resource growth; exact-RC sustained PostgreSQL, application-loop, worker, queue, lock, error and leak measurements UNVERIFIED. |
| 7 | Active-work replica kill/restart with drain/fencing/recovery | UNVERIFIED: no new in-flight Attempt/physical-effect correlation. Process exit/rejoin and terminal Run counts are insufficient. |
| 8 | Long-running exact RC artifact/configuration soak | BLOCKED: no designated immutable promotion RC/configuration supplied. Current harness always rejects artifact equivalence (`run_soak.py:635`); inspected historical duration is below four hours. |
| 9 | Findings filed/reclassified to earliest broken invariant | PARTIAL: existing local evidence dispositions preserved. External filing UNVERIFIED and prohibited in this lane. No new load run or new load finding is claimed. |
| 10 | Machine/human evidence tied to exact hashes | PARTIAL: historical preflight machine/human files are preserved unchanged. Qualifying RC-artifact/configuration evidence UNVERIFIED. |

The prior H3 shared-store overclaim is already corrected in `m3a-soak-evidence.md:174`; no duplicate prose repair is needed. Accepted per-principal rate semantics do not authorize inventing a second authorization path here, and documented process-local enforcement does not waive #860's aggregate non-bypass criterion. Its mismatch must be resolved by the owning rate-limit/release lanes before acceptance.

## Final checkpoint and required next action

**BLOCKED; not promotion approval.** Only this handoff changed. No production code, runtime configuration, tests, raw evidence or ledger was changed. The explicit CI-repair gate needs no repair at this head; passing it cannot resolve the acceptance block.

The release owner must designate the immutable RC/configuration, resolve the aggregate rate-limit mismatch, complete representative production-path workloads and physical-effect/recovery oracles, and publish a new >=4-hour exact-artifact soak. Any intervening code/runtime-config change requires a new soak. Another host-preflight run cannot meet that requirement.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and production-path sustained evidence}`. CI-repair validation is complete; issue #860 remains incomplete. This handoff is the local writer commit checkpoint. No GitHub mutation occurred.
