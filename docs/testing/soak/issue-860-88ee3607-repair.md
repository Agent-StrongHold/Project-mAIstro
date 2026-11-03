# Issue #860 — repair checkpoint (88ee3607)

## Frozen scope and initial evidence

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`. Verified starting HEAD `3bb3823967738883ada1f2d1d3378a42ece96afc`
and supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2` resolves.
Initial worktree clean; no uncommitted work to salvage.

Process only the supplied historical schema-test failure, exact vulture gate,
and issue acceptance against existing production seams and soak tests. Candidate
edits frozen to this report, `quality/vulture-baseline.json` if a fresh scan
requires reviewed retained identities, and the schema fence implementation/test
and accompanying inventory note only if the historical failure reproduces.
No speculative changes or GitHub mutations. Existing branch work preserved.

Writer-role assumption: lane says repair and requires a commit. No current-job
`check-*.log` files were present at initial inspection. The supplied prior log
`/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log` reports
24 DDL statements versus 21 expected in the schema-fence test, not a scanner
finding. Current source already explicitly expects the three additional
validation audit columns; this observation is not yet a test result.

The captured issue body has ten acceptance criteria. Existing profile explicitly
calls the host-process driver a preflight emulator, not an exact production RC.
An exact RC designation cannot be assumed from branch HEAD. Read-only context
inspection is limited to supplied issue/PR evidence, relevant ADRs, production
schema/rate/admission seams, soak runner/tests/profile, and relevant gate files.

## Validation

Fresh execution (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1323 findings / 1323 reviewed identities, zero unclassified or forbidden; gate-selected base `4aa68edc0b6b`. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — PASS: 103 passed, 6 skipped in 2.59s. Supplied historical failure does not reproduce. Skipped PostgreSQL tests are not integration evidence.

Current failure item completed: no fresh scanner/schema regression to repair.
Acceptance review remains in progress; no production or test edits justified.

Read ADR-081 (Proposed, not accepted authority), ADR-085 (Accepted),
ADR-081426-1f7c (Accepted), and ADR-082526-b36a (Accepted). Preserve canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Physical execution identity is
Attempt; a unique admission is not proof of unique physical work. Lease renewal
and reclamation remain canonical responsibilities, not a soak-owned scheduler.
ADR-085 requires per-principal keys but does not establish a shared replica
budget. The executed production middleware test observes `[200, 200, 429]` on
each of two instances for the same identity, both authenticated and pre-auth.
This falsifies a shared-budget interpretation; it does not prove all concurrent
security behavior or justify inventing a second authorization path.

Supplied parent #89 requires promotion of the identical tested RC tree, but its
captured body does not designate an immutable artifact/configuration. The linked
open PR body is a draft claim-stake, not RC designation. Existing profile admits
missing representative surfaces and explicitly rejects host preflight as RC
proof. Repeating a short preflight cannot resolve that blocker.

Additional fresh checks (1200-second timeout), all PASS:

- `uv run ruff check .`
- `uv run ruff format --check .` — 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`
- `uv run python scripts/check-execution-lifecycles.py` — 19 classified/discovered.
- `git diff --check`

CI argument forms inspected in `.github/workflows/quality.yml`, `ci.yml`, and
`vulture-ratchet.yml`. No gate changes. Production installs the tested middleware
at `packages/maistro-server/src/maistro_server/main.py:648`. The task-route
backpressure handler at `api/tasks.py:117` is exercised through the real router,
queue and in-memory canonical spine, not a deployed multi-replica database.

## Acceptance review

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` acknowledges absent concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and Goal/background reconciliation. Applicability needs a designated RC configuration. |
| 2 | At least two application replicas | **UNVERIFIED for deployed RC**. Executed tests use two real middleware instances in ASGI transports, not two immutable promoted images. |
| 3 | Sustained saturation, growth, reclaim, retry, leaks, shutdown | **UNVERIFIED**. No sustained production workload executed this round. Sampler subprocess regression passed; it cannot establish long-window production behavior. |
| 4 | No duplicate physical work | **UNVERIFIED**. Executed receipt-probe tests reject duplicate/missing admission IDs, but do not observe physical Attempt effects under contention. ADR-081426-1f7c prevents treating Run receipt uniqueness as physical execution uniqueness. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | **Shared-budget interpretation falsified** by executed `tests/test_soak_promotion_gates.py:439`: same identity receives independent `[200, 200, 429]` allowances on each production middleware instance. Local enforcement and task 429/retry behavior pass; broader concurrent security acceptance **UNVERIFIED**. |
| 6 | Required metrics and explicit thresholds | **UNVERIFIED at RC grade**. Profile defines thresholds; sampler tests cover process-group RSS/fds/missing measurements. Application-loop lag, pool saturation/reclaim and long-window observations remain absent. Driver-loop lag is not application-loop lag. |
| 7 | Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Executed boot-cleanup tests are not evidence of physical-work recovery. No active-work RC restart performed. |
| 8 | Long-running exact RC/configuration and rerun after changes | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration established. `scripts/soak/run_soak.py:730` always rejects host preflight as exact-RC evidence; executed CLI tests prove even four-hour synthetic preflight evidence fails. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED externally**. Local findings retained here; GitHub mutations prohibited and not performed. |
| 10 | Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC**. This is a validation checkpoint, not a new hash-tied production soak pack. Historical artifacts are not certified for current HEAD. |

## Final handoff

**BLOCKED**, not integration approval. The historical test failure and prescribed
scanner failure do not reproduce. No actual finding warrants a code or ledger
repair. Only this report changes; no tests added/removed, so inventory delta is
zero and no inventory note is needed. The inherited branch diff remains intact
and is not certified by this bounded validation.

Next required inputs: designate the immutable RC image/package/configuration,
justify workload applicability, and resolve aggregate rate-budget semantics.
Then run the production-topology long soak with physical Attempt-effect
correlation, complete telemetry and active-work restart. Do not repeat this
CI-only lane expecting it to prove those missing acceptance criteria.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 fresh validation commands. Local commit records this checkpoint only.
