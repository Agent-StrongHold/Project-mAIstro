# Issue #860 repair — job 2f4c1a13

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `eed38de35e3b3b472aa8fb80454531fd2d27815c`, supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean. No salvage required; no GitHub mutations.
- Review surfaces: repository instructions, relevant execution/deployment ADRs,
  `scripts/soak/`, adjacent soak tests, production paths they exercise,
  supplied dispatch/prior-result/prior-check evidence, CI gate implementation.
- Edit surfaces: this report; `quality/vulture-baseline.json` and identities
  reported by the required scan only if an actual mismatch is reproduced.
  Any necessary regression test also requires an inventory note.
- No current-job `check-*.log` files were present at initial snapshot.
- Prior result reports BLOCKED, not a merge conflict. Assumption: audit the
  current committed state without a speculative develop merge or RC selection.

## Progress

Initial state and complete issue acceptance text inspected. Prior claims are
not treated as verification.

- Required exact vulture scan passed: 1323 reviewed identities, 1323 findings,
  zero unclassified. No ledger change is supported by current evidence.
- Supplied historical `98a11313.../check-3.log` reports a 24-versus-21 schema
  statement mismatch. Current focused pytest rerun: **111 passed, 6 skipped**
  (2.43s); that failure did not reproduce. Skips require a migrated PostgreSQL
  DSN and are not acceptance evidence.
- Read of guessed `docs/adr/ADR-085-auth-rate-limiting.md` returned ENOENT:
  not found; skipped. Resolved actual ADR filenames locally before continuing.
- Load profile explicitly calls the runner a host-process preflight and lists
  missing production workloads; no exact-RC validation can be inferred from
  passing harness unit tests.

## Architecture and reconciliation

Read `AGENTS.md` and accepted ADR-073126-c4e1 (release/versioning),
ADR-082526-b36a (renewable leases/fencing), and ADR-085 (principal-keyed rate
limits). Keep `Goal -> Graph -> Run -> NodeRun -> Attempt` authoritative.
ADR release provenance cannot be satisfied by selecting an arbitrary local
build. Restart/rejoin cannot substitute for lease and physical-effect fencing.
The middleware explicitly documents process-local budgets; that narrower
contract is not evidence for #860's replica-selection non-bypass criterion.
No alternate execution, event, or authorization authority was introduced.

## Commands and outcomes

All validation commands used 1200-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1323/1323 exact reviewed identities, zero unclassified. Arguments
  match `.github/workflows/vulture-ratchet.yml:82`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — PASS, 111 passed / 6 skipped. No full-tree pytest attempted.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py` — PASS, 17 suites,
  31128 unique test identities. No tests added; no inventory delta needed.
- `uv run python scripts/check-deployment-claims.py` — PASS; this checks
  component existence, not deployed concurrency or production readiness.

## Acceptance audit

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic. `docs/testing/soak/m3a-load-profile.md:152` documents missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker traffic. |
| Two deployed application replicas | **UNVERIFIED.** Executed tests use ASGI middleware instances and a wrapper/child sampler; no deployed RC topology was exercised this round. |
| Sustained saturation, growth, reclaim, retry/backoff and leaks | **UNVERIFIED.** Sampler and bounded accounting regression tests pass, not sustained workload observation. Six database tests were skipped without a migrated DSN. |
| Physical-work uniqueness across replicas | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1068` cancels an unexecuted schedule-probe Run. Deduplicated admission is not proof of unique physical work or Goal reconciliation. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent replica allowances reproduced.** `tests/test_soak_promotion_gates.py:439` exercises production middleware with the same identity on two instances: each yields 200, 200, 429 independently. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates an in-memory limiter per instance. Task backpressure tests prove the narrower retryable-429 path only. |
| Complete telemetry with thresholds | **UNVERIFIED.** Sampler regression passes, but `scripts/soak/run_soak.py:1410–1422` samples driver event-loop lag, not application event-loop latency; no current complete deployed time series validated. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED.** Gate/drain unit checks pass, not a deployed kill/restart with a physical-effect oracle. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Assignment supplies source refs, not a designated immutable RC artifact/configuration. `scripts/soak/run_soak.py:730–741` rejects host preflight as exact RC. Executed synthetic four-hour CLI tests verify rejection only; no four-hour run occurred. |
| Findings filed/reclassified before promotion | Local evidence recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. The historical schema failure is not newly reproduced: current expectations include the three audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`. |
| Hash-bound machine/human RC evidence | **UNVERIFIED.** This source-linked validation report is not an image/package/config-bound deployed soak evidence pack. |

## Disposition and handoff

**BLOCKED.** Only this report changed. All inherited work remains intact; no
source, test, ledger, grant, or gate changes are justified by the supplied
historical failure and current scan. This is a validation checkpoint, not an
implementation fix or integration approval.

Next prerequisite: release owner designates immutable RC artifact/configuration
and workload applicability. Then complete deployed workloads, physical-effect
and recovery oracles, and application telemetry; reconcile replica-budget
semantics through the existing authority; run the unchanged >=14400-second
multi-replica profile and publish hash-bound evidence. Do not dispatch another
schema/vulture repair as a substitute for those missing acceptance surfaces.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0; one missing-document lookup recorded above.
`git diff --check` passed; this report is committed locally after a staged
whitespace check. No push or GitHub mutation.
