# Issue #860 — d9bbb077 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `fa54b33111cec636d9f97c7d962bb0a0e3341341`; supplied base: `f11dfd0c559225b64098252677e843f23c3be299` (both resolved).
- Initial working tree clean; no incoming uncommitted work to salvage.
- Process the supplied prior failure/result, existing `scripts/soak/run_soak.py`, its promotion tests, relevant production persistence/task tests, load profile/evidence, CI gate and relevant ADRs. Edit only an evidenced issue-860 defect, a reviewed vulture identity if the mandated gate reports one, and this handoff (inventory note if tests change).
- No GitHub mutation or re-enumeration. Current job directory initially contains no `check-*.log`; execute validation locally.
- Assumption: this is a writer CI-repair round, not permission to substitute local smoke tests for the exact-RC long soak required by acceptance.

## Progress

- Supplied `98a11313/check-3.log` read: schema fence expected 21 statements but observed 24. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. Reported failure is not reproducible at the assigned HEAD; PostgreSQL-dependent skips are not evidence.
- Mandated `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1,328 findings / reviewed identities, zero unclassified or never-allowlist. No ledger amendment justified. Gate selected trusted base `72f5dedd3db3`, candidate `fa54b33111ce`.
- Supplied prior result read: BLOCKED on exact RC/workload/soak prerequisites, not a develop-sync conflict. No merge needed. Current acceptance review follows below.

## Architecture and additional validation

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (store-owned execution fencing), ADR-082526-b36a (lease renewal/reclaim), and ADR-085 (per-principal rate limiting). The later reclaim contract extends the earlier fencing ADR: recovery is not absent by definition, but still needs production soak evidence. No competing scheduler, state store, event or authorization authority is introduced.

The schema expectation now independently lists the three Gauntlet audit columns as well as the other DDL, matching the guarded production upgrade. Do not delete those columns or weaken the test to match an obsolete failure log.

Fresh commands, each with a 1,200-second timeout:

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,159 files formatted |
| `uv run python scripts/check-deployment-claims.py` | PASS, static deployment claims only |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |

No new or modified tests; no inventory delta. These checks do not certify the full inherited branch or prove exact-RC sustained concurrency.

## Production reachability and acceptance evidence

`maistro_server/main.py:648` installs the tested `RateLimitMiddleware`; lines 735/755 install the task router. `api/tasks.py:117` maps canonical admission backpressure to 429/Retry-After. The passing backpressure test uses the real router, queue and canonical in-memory spine, checks principal isolation and admission after freeing a slot, but intentionally starts no executor.

`tests/test_soak_promotion_gates.py:439` freshly demonstrates that one identity gets `[200, 200, 429]` independently on both production middleware instances (authenticated and unauthenticated cases). `api/rate_limit.py:31` explicitly documents process-local N-times aggregate allowances. Local rate enforcement therefore does not establish replica-selection non-bypass. Do not introduce another authorization path or silently redefine acceptance to conceal this gap.

A fresh `uv run python` importlib probe loaded the current runner and evaluated `evidence/m3a-round30-shakedown.json`: `failed_promotion_checks` returned `['sustain_duration', 'exact_rc_artifact']`, with assertions requiring both failures. `preflight_artifact_check()['ok'] is False` also passed. This verifies current rejection of historical evidence, not a new soak. `git diff --check` passed.

| Issue acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:147` lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker reconciliation. No selected exact RC/configuration was provided. |
| Two production application replicas | **UNVERIFIED** for this candidate. Two middleware instances in a unit test are not a production deployment. |
| Sustained saturation, queue growth, reclaim, retry/backoff, leaks and shutdown/restart | **UNVERIFIED**. The freshly evaluated historical evidence fails the minimum duration gate. |
| No duplicate physical work across replicas | **UNVERIFIED**. Schedule probe admission followed by cancellation is not physical execution proof; the API test also does not start an executor. Accepted reclaim/fencing contracts do not replace load evidence. |
| Rate/security/degraded behavior resists replica selection | **UNSATISFIED as proof**. Passing tests reproduce independent replica allowances; local backpressure works but does not prove a shared allowance or full concurrent security behavior. |
| Complete PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED**. Profile distinguishes driver-loop lag from application-loop lag and records missing production worker, pool-saturation and reclaim observations. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. No active-work exact-RC restart executed this round. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**. Current runner fails artifact eligibility by construction (`run_soak.py:730`); historical evidence freshly fails both artifact and duration gates. Profile requires at least four hours. |
| Findings filed/reclassified to earliest broken milestone | **UNVERIFIED** completeness. This report records blockers locally; GitHub filing/mutations are prohibited. |
| Published machine/human evidence with exact image/package/commit/config hashes | **UNVERIFIED** for this candidate. Validation report is not a hash-bound production soak. |

## Disposition

**BLOCKED for acceptance, not an outstanding reproduction of the supplied CI failure.** Only this handoff changed. No source, tests, grants or ledgers were changed, and all inherited work is preserved. No develop-sync conflict exists in this worktree.

Next requires an explicitly selected immutable RC image/configuration, a representative workload covering or justifiably scoping the missing production surfaces, and a promotion-capable runner. Then run the minimum four-hour workload with active-work restart, canonical physical-work/fencing/reclaim observations and full production telemetry. Publish hash-bound evidence and reclassify any observed failures. Repeating the same CI-repair assignment cannot supply that evidence; do not weaken the gates or call another host preflight a promotion soak.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1. Local commit is the handoff only, not integration approval. No push, PR, merge or closure action.
