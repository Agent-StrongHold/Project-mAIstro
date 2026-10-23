# Issue #860 — e3f673f9 repair handoff

## Scope and decision

Checked issue #860 only in `/home/dev/Git/wt/auto-860`, starting at
`df6d0768883909d792696de56109c9a4519a99db` (clean); supplied develop base
`b58650089e1bfa48d95a608916f21365f999e42a` resolves. Read the supplied dispatch
snapshot, prior result and failure log. No current-job `check-*.log` existed
at initial inspection. No uncommitted work, conflict, or missing Git ref required
salvage or synchronization. No GitHub mutations performed.

**BLOCKED on production acceptance, not on a reproduced CI failure.** The
mandated vulture scan passes without any unbanked identities. The supplied
`98a11313167b41a98a420abfda80c292/check-3.log` instead reports 24 schema DDL
statements versus 21 expected; the current test independently includes the
three Gauntlet audit columns and passes. Neither a ledger edit nor another
schema change is justified by current evidence. This handoff is the only change;
no tests changed, so no inventory delta is required.

## Architecture and reachable behavior

Read repository instructions and accepted ADR-081226-a66b (canonical lifecycle),
ADR-081626-f383 (store-owned fencing), ADR-082526-b36a (renewal/reclaim), and
ADR-085 (per-principal limiting). The later reclaim ADR extends the earlier
fencing boundary; it does not eliminate the need to observe recovery under load.
No competing scheduler, execution authority, store, event or authorization path
was introduced.

`packages/maistro-server/src/maistro_server/main.py:648` installs the production
`RateLimitMiddleware`; lines 735/755 install the task router exercised by the
backpressure test. The real middleware constructs an in-memory limiter per
instance (`api/rate_limit.py:93`). Fresh execution of
`tests/test_soak_promotion_gates.py:439` demonstrates that the same authenticated
or unauthenticated identity receives `[200, 200, 429]` independently on both
instances. This proves local enforcement, not a shared replica-independent
allowance. ADR-085's principal-keying requirement is not an acceptance waiver.

The backpressure test uses the real task router, queue and canonical spine,
proves 429/Retry-After on a full principal ceiling, isolation from another
principal, and admission after freeing a slot. It deliberately starts no
executor and therefore cannot prove physical execution uniqueness.

## Fresh validation

All commands used a 1,200-second timeout (the final Git checks shared the probe
command). These are focused checks, not full inherited-branch certification.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,328 findings/reviewed identities; zero unclassified or never-allowlist; gate selected base `72f5dedd3db3`, candidate `df6d07688839` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped PostgreSQL cases are not evidence |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,159 files |
| `uv run python scripts/check-deployment-claims.py` | PASS: static deployment claims only |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python` importlib probe of current runner and `evidence/m3a-round30-shakedown.json` | Asserted historical evidence fails `sustain_duration` and `exact_rc_artifact`; actual failures exactly those two. Also asserted `preflight_artifact_check()['ok'] is False` |
| `git diff --check` | PASS before handoff; repeated before commit |

## Acceptance review

| Criterion | Evidence and remaining disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:147` records missing user/Workspace population, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker traffic. Selected RC applicability remains unspecified. |
| At least two production application replicas | **UNVERIFIED** for this candidate. Two middleware instances are not production replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff, leaks and shutdown/restart | **UNVERIFIED**. Historical evidence freshly fails duration eligibility; no long production run executed. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission tests and a schedule probe cancelled before execution cannot prove physical Attempt fencing/recovery. |
| Concurrent rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED / unresolved allowance gap**. Fresh production-middleware tests reproduce independent allowances. Task backpressure passes locally, not a cross-replica security soak. |
| PostgreSQL latency/usage/locks, application-loop lag, workers/RSS/FDs, queue/errors with thresholds | **UNVERIFIED** at production grade. Profile explicitly distinguishes driver-loop lag from application-loop lag and notes missing pool/reclaim/worker observations. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**. No exact-RC active-work restart executed. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**. `scripts/soak/run_soak.py:730` rejects this host-process runner as exact-RC evidence; current probe confirms it. Historical evidence also fails the four-hour duration requirement. |
| Findings filed/reclassified to earliest broken milestone invariant | **UNVERIFIED** completeness. Blockers recorded locally; external filing is prohibited in this assignment. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED** for this candidate. This validation report is not a production soak artifact. |

## Required next action

Supply the immutable RC image and runtime configuration intended for promotion,
complete or explicitly scope its representative workload, and provide a
production-topology runner with the missing physical-work and telemetry probes.
Then execute the minimum four-hour soak with active-work restart and publish
hash-bound evidence. Resolve the replica allowance contract without inventing a
second authorization path. A further identical vulture repair dispatch cannot
supply these prerequisites, and a longer host preflight cannot certify them.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
Only this handoff is committed locally; no integration approval or issue closure.
