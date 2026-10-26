# Issue #860 repair checkpoint — ecb96b99

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `35c1ff4d7d5c901a835b57bc9775daeec0826b20`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree was clean. No incoming changes require salvage.
- Investigate the supplied schema-fence failure in
  `packages/maistro-core/tests/persistence/test_pg_learnings.py` against
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`.
- Validate existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, adjacent backpressure tests, and the
  required vulture scan. Amend `quality/vulture-baseline.json` only if the
  executed scan identifies reviewed retained debt.
- This report and an inventory note (only if tests change) are the documentation
  write scope. Other files are read-only architecture/acceptance evidence.

## Initial evidence and assumptions

- No `check-*.log` files were present in this job directory at initial snapshot.
- Supplied prior `98a11313.../check-3.log` reports schema-fence assertion failure:
  24 executed statements versus 21 expected. This is historical evidence,
  not assumed to reproduce at current HEAD.
- Supplied prior result reports BLOCKED on exact-RC evidence and independent
  replica rate allowances. These claims require fresh validation.
- Writer role applies. No GitHub mutations or release-candidate designation.

## Progress

- Historical schema-fence failure does **not** reproduce: current test explicitly
  expects all three Gauntlet audit columns. Focused pytest command passed:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — **103 passed, 6 skipped** in 2.53 seconds. Skips do not prove PostgreSQL
  integration or a deployed soak.
- Required exact vulture invocation passed:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1,323 findings / 1,323 reviewed identities; zero unclassified or
  never-allowlist identities. No evidence supports changing the ledger.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed
  (3,270 files already formatted).
- Both production-middleware replica-selection cases passed: the same identity
  receives 200, 200, 429 independently from each middleware instance. This
  demonstrates local budgets, **not** selection-proof aggregate enforcement.
- All three four-hour preflight CLI regressions passed by rejecting missing,
  null, or host-preflight artifact evidence (exit 1 expected by tests).
- Existing profile explicitly lists missing representative workloads and
  requires an exact immutable RC deployment. Local tests cannot fill those gaps.

- `uv run python scripts/check-ratchet-provenance.py` passed: 53 consumers
  have explicit provenance. Two non-fatal AST invalid-escape warnings occurred.
- `uv run python scripts/check-shipped-surface-truth.py` passed: matrix complete.
- `git diff --check` passed.
- Commands used long (1,200-second) validation timeouts. No production soak,
  service deployment, or PostgreSQL integration run was executed this round.

## Architecture and reachable behavior

Read repository `AGENTS.md`, `docs/README.md`, ADR-081 (Proposed, not an accepted
waiver), accepted ADR-081626-f383 (Attempt lease/fencing), ADR-082126-f69c
(recurrence produces canonical Runs), and ADR-085 (per-principal rate limits).
The required model remains Goal -> Graph -> Run -> NodeRun -> Attempt. No new
scheduler, execution authority, store, event authority, or authorization path
is introduced. Admission uniqueness cannot be substituted for physical-work
fencing. The documented process-local rate scope is not proof of the issue's
stronger replica-selection requirement; it needs explicit disposition, not an
unilateral policy change in a scanner repair.

Production `PgLearningStore.ensure_schema` takes the advisory lock before all
24 DDL statements inside one transaction; the current independent expectation
includes `validated_evaluator_version`, `validation_run_ids`, and
`validation_content_hash`. The historical 21-statement expectation is obsolete.
The existing backpressure test reaches `POST /tasks` through the actual queue
and canonical spine, fills the principal ceiling, verifies 429 + Retry-After,
checks another principal, then verifies admission after releasing a slot. It
passes but is not a multi-process durability/recovery test.

`run_soak.py:730` always labels this runner's host-process artifact insufficient.
Its live `main_async` emits that failed check, and the CLI regressions verify
that duration cannot override it. `_terminalize_probe_run` at line 1044
explicitly cancels the schedule probe's queued Run without physical execution.
`RateLimitMiddleware` at `api/rate_limit.py:93` constructs a fresh in-memory
limiter per instance; the passing replica-selection tests exercise this actual
middleware and its canonical principal resolver, not a fake limiter.

## Acceptance assessment — all ten frozen issue criteria

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md` explicitly identifies one-key degraded preflight and missing users/Workspaces, fan-out, successful tool/model work and Design/Canvas/background-worker applicability. RC/configuration selection remains unresolved in this round. |
| At least two deployed application replicas | **UNVERIFIED**. Two middleware instances were tested, not two deployed RC artifacts. |
| Sustained saturation, queue growth, reclaim, retries, memory/descriptor/process leaks | **UNVERIFIED**. Sampler and accounting regressions passed; no sustained operational observations collected. |
| No duplicated physical work across schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Admission receipt regressions passed; the schedule probe cancels without execution (`run_soak.py:1044`). No physical-work or reconciliation soak proof. |
| Rate/security/degraded non-bypass under replica selection | **UNVERIFIED overall; independent allowance counterexample reproduced**. Both cases at `tests/test_soak_promotion_gates.py:439` accept two requests then reject the third independently on each instance for the same identity. Local enforcement cannot prove a shared principal budget. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Profile has thresholds and tested process-group sampling, but driver loop lag is not application loop lag, and no complete RC telemetry series was executed. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED**. Cleanup regressions pass, not active physical-work interruption/recovery. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. No >=4-hour exact-RC run; preflight artifact rejection remains enforced. A longer host-process run would still fail. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external milestone disposition **UNVERIFIED**. No GitHub mutations performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED at promotion grade**. This checkpoint identifies tested source HEAD, not an executed image/configuration-bound soak. |

## Handoff

**BLOCKED**, not integration approval. Only this report changes. No tests added
or modified, so no inventory delta; no production or ledger amendment justified
by the executed checks. The supplied failure is already repaired and the exact
debt gate has no new identities. This round cannot resolve the operational
blocker by cosmetic code edits or another scanner rerun.

Next: designate the immutable RC and supported configuration, settle the
replica-selection rate contract, implement/execute representative canonical
physical-work scenarios with complete telemetry, and run the unchanged exact
artifact for the profile's >=4 hours with active-work interruption and recovery.
Do not retry the same CI-repair hypothesis without a new failing command or
new operational inputs. No deployment or promotion is authorized here.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; validation errors 0;
blocked 1. Historical failure checked and non-reproducing; RC acceptance remains
unverified.
