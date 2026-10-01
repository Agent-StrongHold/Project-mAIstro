# Issue #860 — round 16 CI repair and acceptance verification

## Frozen scope

- Assigned issue only: #860, branch `auto-860`, starting HEAD
  `5ebefb809094e16a4993b69ce4dcc48e0b5e4eed`, base
  `b9bcdd255fa07371653e236d851c1a9a12649149` (both resolved locally).
- Worktree was clean. No salvage or develop-conflict repair required.
- Process only the assigned exact-debt-ledger gate and the ten acceptance
  criteria in the supplied issue snapshot. No issue/PR enumeration or mutations.
- Planned writable files: `quality/vulture-baseline.json` (reviewed retained
  identities only), this handoff. Existing #860 source/tests/profile/evidence and
  relevant ADRs are read/validation scope; do not replace historical evidence.
- Prior job result inspected: reports BLOCKED, not promotion evidence.
- Current job directory has no `check-*.log` files. Driver checks cannot be
  claimed; run fresh checks below.

## Ambiguity and working assumption

The lane is a writer/CI-repair assignment, not a read-only verifier. The explicit
ledger exception applies. No immutable RC image/configuration is identified in
the assignment; no substitute host-emulator run can satisfy the exact-RC soak.
Do not redesign rate limiting or launch an undesignated promotion artifact.

## Progress

- Requested exact-debt-ledger gate executed with 1200-second timeout: PASS,
  1402 reviewed identities / 1402 findings; zero unclassified and zero
  never-allowlist findings. No unbanked identities exist to review/amend, so no
  ledger or production-code edit is justified.
- Inspected the existing profile: explicitly a host-process preflight, not
  an exact production artifact. The prior round already corrected the H3
  shared-limiter claim.
- Focused pytest: **102 passed, 5 skipped in 9.52s**. All skips require
  `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof is claimed.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  2624 files formatted. Suite inventory gate: PASS, `tests/` = 4198.
- Read accepted runtime, Attempt-fencing, rate-policy, absent-metric and
  quality-governance ADRs. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
  no alternative scheduler/store/security authority added. Admission uniqueness
  is not physical-effect uniqueness, missing application metrics are not zero,
  and principal identity does not imply cluster-shared limiter state.
- The regression at `tests/test_soak_promotion_gates.py:439` freshly observes
  `[200, 200, 429]` independently on both middleware instances for the same
  authenticated principal or unauthenticated client. The middleware is installed
  in production at `maistro_server/main.py:478`. This falsifies aggregate-budget
  non-bypass, but is not a deployed multi-replica soak.
- Task-backpressure regression mounts the production task router and canonical
  in-memory spine; verifies per-principal 429/Retry-After, other-principal
  admission and recovery after slot release. It starts no physical worker.
- Process sampler regression observes a real child's 32 MiB/16-descriptor
  growth; its PostgreSQL seam is mocked. No database-load inference is valid.
- Fresh `uv run python -` import/execution of `failed_promotion_checks` rejects
  each of the four frozen historical JSON files for `sustain_duration` and
  `exact_rc_artifact`. Round 5 records 90.17 seconds, round 6 records 90.43
  seconds, versus 14400 required. Earlier files lack the top-level observed
  duration. Current `preflight_artifact_check()['ok']` is asserted false.
  This is new evaluator execution over historical inputs, not a new soak.
- `git diff --check`: PASS before final report completion.

## Commands executed

All validation used 1200–1800-second timeouts:

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite tests/
git diff --check
```

The inline `uv run python -` evaluator inspected exactly:
`m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
`m3a-round6-shakedown.json` in `docs/testing/soak/evidence/`. Assertions required
both duration and artifact failures for each, plus the current host-preflight
artifact rejection. No historical JSON was modified.

## Acceptance disposition

| # | Criterion | Executed evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC profile | **PARTIAL / UNVERIFIED**. Read `m3a-load-profile.md`; the remaining-gaps section excludes concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal/background activity. No designated RC to justify exclusions. |
| 2 | At least two application replicas | **UNVERIFIED**. `deploy/docker-compose.prod.yml:27-62` declares two services; no designated production artifacts were started. ASGI middleware instances are not deployed replicas. |
| 3 | Sustained saturation, queues, reclaim, retries, leaks, shutdown | **UNVERIFIED**. Fresh evaluator rejects all historical durations. Sampler regression is not sustained application load. |
| 4 | No duplicate physical work, including schedules/Run/Attempt/Goals | **UNVERIFIED**. Admission/backpressure tests pass but do not execute physical work across replicas; one-occurrence claim probes cannot establish sustained reconciliation/fencing. |
| 5 | Rate/security/degraded non-bypass across replicas | **NOT MET** for aggregate rate allowance. Executed production-middleware counterexample proves independent allowances. Security/degraded exact-RC concurrency behavior remains **UNVERIFIED**. |
| 6 | Complete metrics with explicit thresholds | **PARTIAL / UNVERIFIED**. Profile and sampler tests exist; application-loop latency, database saturation/lock contention, worker census and long-window growth/error series are not measured in an RC run. Five live PG tests skipped. |
| 7 | Active-work kill/restart and fenced recovery | **UNVERIFIED**. No fresh kill/restart performed; historical exit/rejoin does not correlate physical effects to in-flight Attempts. |
| 8 | >=4-hour exact RC/configuration soak, rerun on changes | **BLOCKED**. Immutable promotion artifact/configuration is not supplied. Current driver always rejects host topology (`scripts/soak/run_soak.py:635`); latest historical duration is 90.43 seconds. |
| 9 | Findings filed/reclassified to earliest invariant | **PARTIAL / UNVERIFIED**. Human pack preserves F11/F12 classification as M3-A evidence-validity failures; no new load findings produced. External filing not verified or performed; GitHub mutations prohibited. |
| 10 | Human/machine evidence tied to exact hashes | **PARTIAL / UNVERIFIED**. Historical packs preserved and mechanically rejected; no qualifying exact-image/configuration sustained evidence published. |

## Final checkpoint and required next action

**BLOCKED — not integration approval.** The assigned CI gate is already green;
no evidence supports a source/ledger repair. Only this handoff changes. No new
tests, inventory delta, runtime/configuration change, or claimed load result.
The corrected H3 text is already in the starting HEAD and was not re-edited.

Release owner must designate an immutable RC image/configuration; owning lanes
must resolve the aggregate rate-policy mismatch and complete production-path
workloads plus physical-effect/fencing oracles. Then run and publish >=4 hours
on that exact topology, repeating after any code/runtime-config change. Another
host preflight or repeated ledger-only repair cannot resolve these blockers.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC,
representative workloads, and exact-artifact sustained evidence}`. CI gate
validation is complete; issue #860 acceptance is not. No remote actions taken.
This handoff is committed locally as the writer checkpoint.

