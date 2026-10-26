# Issue #860 — 1635a91b repair handoff

## Frozen scope and outcome

Only #860 was checked in `/home/dev/Git/wt/auto-860`, branch `auto-860`,
starting at `f157186fa7a15c85fbdcfb804f61837a690ed3ce` (clean), against the supplied
base `34795962548a33f6b6f7e1234dcea201a9df96ef`. No sync conflict existed.
The supplied dispatch snapshot and prior result/failure log were inspected;
no current-job `check-*.log` files existed at initial inspection.

**BLOCKED on production acceptance, not a reproduced CI failure.** The supplied
`98a11313167b41a98a420abfda80c292/check-3.log` expected 21 schema statements instead
of 24. The current test already independently includes the three Gauntlet audit
columns (`test_pg_learnings.py:173`), and passes afresh. The mandated vulture scan
also passes. No code or ledger amendment is justified. This report is the only
change; no tests were added or changed, so no inventory delta is needed.

## Architecture and acceptance evidence

Read repository instructions and accepted ADR-081226-a66b (canonical lifecycle),
ADR-081626-f383 (store-owned fencing), ADR-082526-b36a (renewal/reclaim), and
ADR-085 (principal limiting). The later reclaim contract extends the earlier
fencing boundary; neither permits substituting admission counts for physical-work
uniqueness. ADR-081 was also read but is **Proposed**, not an accepted waiver.
No execution, scheduling, persistence, event or authorization authority changed.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:648`.
`maistro_server/api/rate_limit.py:93` constructs a limiter per instance. Freshly
executed `tests/test_soak_promotion_gates.py:439` confirms the same identity gets
`[200, 200, 429]` independently on each instance, authenticated or not. This is
local enforcement, not proof of replica-selection non-bypass. The task router
backpressure test uses the canonical spine but deliberately starts no executor.

| Issue acceptance criterion | Current evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md:147` lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker traffic. Applicability to the selected RC is not established. |
| At least two production application replicas | **UNVERIFIED** for this candidate. `deploy/docker-compose.prod.yml` declares two replicas; ASGI middleware instances are not a production deployment. |
| Sustained saturation, queues, reclaim, retries, leaks and restart | **UNVERIFIED**: no long production run executed. Historical round-30 evidence freshly fails duration eligibility. |
| No duplicate physical work across replicas | **UNVERIFIED**: admission tests do not execute physical work; the profile's schedule probe cancels its queued Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**, with independent allowances reproduced by the production-middleware test above. Local task backpressure passes. |
| PostgreSQL, application-loop, worker, RSS/FD, queue/error telemetry and thresholds | **UNVERIFIED** at production grade. Profile notes driver-loop sampling is not application-loop sampling and lacks sustained pool/reclaim observations. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**: no exact-RC active-work restart executed. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**: current `run_soak.py:730` always rejects its host preflight as exact RC; fresh probe confirms historical evidence fails both duration and artifact checks. |
| Findings filed/reclassified to earliest broken milestone invariant | **UNVERIFIED** completeness. Blockers recorded here; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED** for this candidate. This report is validation evidence, not a hash-bound production soak. |

## Fresh validation

Commands used 1,200-second timeouts. Logs are in job directory
`/home/dev/maistro/jobs/1635a91bbe13428ea23ade5e4a056a3f/worker-*.log`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,328 reviewed identities / findings; zero unclassified or never-allowlist; gate-selected base `72f5dedd3db3`, candidate `f157186fa7a1` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skips are not PostgreSQL validation |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,159 files |
| `uv run python scripts/check-deployment-claims.py` | PASS: static deployment claims only |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python` importlib probe of current runner against `evidence/m3a-round30-shakedown.json` | PASS: asserted failures exactly `sustain_duration`, `exact_rc_artifact`; asserted current preflight artifact check false |
| `git diff --check` | PASS |

## Required next action

Supply the immutable RC artifact/configuration intended for promotion and a
production-topology workload/runner covering the missing acceptance surfaces.
Resolve the replica allowance contract through the existing authorization path.
Then execute the profile's minimum four-hour soak including active-work restart,
with physical-work probes, complete telemetry and hash-bound evidence. A longer
host preflight or another identical CI-repair dispatch cannot certify acceptance.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
Local handoff only, not integration approval. No GitHub mutations performed.
