# Issue #860 repair checkpoint — 9b234c19

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`.
- Verified starting HEAD `b72e419525fc79aab3d54ab58acb3a89ff7f7e89`; clean index/worktree.
- Assigned base `435dc1937e0407ab4de198ffcced49860bb14ad2` resolves.
- Process the supplied dispatch snapshot, not live GitHub lists.
- Candidate edits: this report and `quality/vulture-baseline.json` only if the
  exact scanner supplies reviewed retained identities. No speculative code edits.
- Inspect existing soak runner/profile/promotion tests, adjacent production rate
  middleware, relevant ADRs and exact-debt gate. Preserve all inherited work.
- No `check-*.log` files exist in the supplied current job directory at start.
  The cited prior check and result are evidence to inspect, not proof of readiness.

## Assumptions

This is a writer CI-repair round. Exact RC designation and deployment inputs must
be established, not inferred from local HEAD. Missing external release evidence
will remain UNVERIFIED; no substitute scheduler or authorization path will be
introduced. Prior BLOCKED is not a develop-sync conflict (starting tree clean).

## Fresh validation

- Exact prescribed vulture command: PASS, 1323 findings / 1323 reviewed
  identities, zero unclassified/forbidden. Gate-selected base `4aa68edc0b6b`.
  Log: `/tmp/860-9b234c19-vulture.log`. No ledger amendment justified.
- Cited historical `check-3.log` is a schema-fence test failure (24 DDL
  statements versus 21 expected), not vulture. Check current schema tests before
  considering a repair; no expansion to unrelated scanner cleanup.
- Profile explicitly identifies the existing runner as a host-process preflight,
  not an exact-RC runner, and enumerates remaining representative-workload gaps.
  This blocks treating deterministic validation as issue acceptance.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — PASS: 103 passed, 6 skipped in 2.44s (1200-second timeout).
  Log: `/tmp/860-9b234c19-tests.log`. The historical failure does not reproduce;
  current expected DDL includes all three validation audit columns. Skipped
  PostgreSQL cases are not live-database evidence.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS (3270 files).
- `uv run python scripts/check-deployment-claims.py` — PASS.
- `uv run python scripts/check-execution-lifecycles.py` — PASS (19 classified).
  All commands above used 1200-second timeouts. Prescribed CI-repair item is
  complete: no fresh scanner or schema failure warrants changing code/ledger.
- `git diff --check` — PASS.

## Architecture and acceptance evidence

Read ADR-081 (Proposed), ADR-085 (Accepted), ADR-081426-1f7c (Accepted), and
ADR-082526-b36a (Accepted). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Physical execution identity is Attempt; unique Run admission cannot prove unique
physical work. Reclamation must remain on canonical lease/heartbeat paths.
ADR-085 specifies principal-keyed limits but does not specify a shared replica
store. Do not waive issue #860's replica-selection requirement by equating it
with local enforcement. No competing execution or authorization path added.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:648`.
Its implementation (`api/rate_limit.py:95`) constructs an in-memory limiter per
instance. Executed `tests/test_soak_promotion_gates.py:439` observes independent
`[200, 200, 429]` allowances for the same identity on each of two instances,
for authenticated and pre-auth requests. This falsifies a shared-budget claim;
it does not establish all security properties of a deployed RC.

The captured parent #89 requires promotion of the identical tested RC but does
not designate its immutable artifact/configuration. Captured PR #1672 body is
only a draft claim-stake. Neither is permission to choose a substitute RC.

| Criterion | Fresh evidence / outstanding requirement |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:152` lists missing users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. Applicability requires selected RC configuration. |
| At least two production replicas | **UNVERIFIED**. Tests exercise two middleware instances, not two promoted images. |
| Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | **UNVERIFIED**. No long-running workload executed this round; sampler tests do not prove runtime behavior over a soak window. |
| No duplicate physical work | **UNVERIFIED**. Admission-probe regression tests pass; Run receipt uniqueness is not physical Attempt-effect uniqueness. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | Shared aggregate-budget interpretation **falsified** by executed middleware test at `tests/test_soak_promotion_gates.py:439`; full deployed concurrency/security criterion **UNVERIFIED**. Existing task backpressure tests pass. |
| Complete required metrics and explicit thresholds | **UNVERIFIED at RC grade**. Profile defines thresholds but lacks application-loop lag and sustained pool/reclaim/resource observations. Driver-loop lag is not application-loop lag. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**. Boot-cleanup tests pass but do not prove recovery of physical work. |
| Long-running exact RC/configuration soak | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration established. `scripts/soak/run_soak.py:730` rejects host preflight as exact-RC evidence; executed promotion tests cover fail-closed behavior. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Findings recorded locally; no GitHub mutations permitted or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC**. This checkpoint is not a production soak pack; inherited artifacts do not certify current HEAD. |

## Handoff

**BLOCKED**. Only this report changes; all inherited work preserved. No tests
added/removed, so inventory delta is zero and no inventory note is required.
No quality ledger edit: exact scanner found no identities requiring amendment.
No production code repair, gate weakening, GitHub mutation or push performed.

Next required input is a designated immutable RC artifact/configuration with a
representative workload and resolved aggregate rate-budget semantics. Then run
the production-topology long soak with Attempt-effect correlation, complete
telemetry and active-work restart. Repeating this CI-only repair without those
inputs cannot prove the issue. The large inherited branch diff is not certified
by this bounded validation.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 fresh validation commands. CI/schema repair check completed with no
reproducible failure. Commit records this checkpoint, not integration approval.
