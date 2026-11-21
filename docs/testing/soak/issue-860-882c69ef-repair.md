# Issue #860 — repair checkpoint 882c69ef

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting head: `1ee5e6417192f61c69e8630a49cfd5d6402e5e3f`.
- Supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Inspect supplied dispatch context, prior result and failed check log, repository instructions, relevant ADRs, `scripts/soak/run_soak.py`, adjacent soak tests, and production paths those tests exercise.
- Run requested exact vulture check and focused acceptance validation. Only amend retained vulture identities if fresh evidence requires it. No unrelated inherited files are repair targets.
- This report is the planned change; source/test/ledger changes require a reproduced defect first.

## Initial evidence

Starting worktree is clean; no salvage required. The job directory contains no `check-*.log` files at startup. The supplied prior result reports BLOCKED, not promotion approval; its claims will be rechecked. No remote enumeration or GitHub mutation is planned.

## Progress

Fresh validation (1200-second timeout) completed:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1323 findings / reviewed identities, zero unclassified or never-allowlist findings. Gate-selected base `4aa68edc0b6b`. No ledger amendment is warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 103 passed / 6 skipped (2.40 seconds). Skips are not live PostgreSQL evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.

Read the supplied prior failed log: the old schema-fence assertion expected 21 statements and observed 24. Fresh execution does not reproduce it. No speculative scanner/test repair is justified.

Exact release candidate/deployment configuration is not yet established; do not infer it from the checkout head. Read the frozen issue body's ten acceptance criteria, repository `AGENTS.md`, and accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; b36a extends f383 with renewal/reclaim rather than authorizing a second recovery scheduler. Principal rate identity remains the canonical security boundary. The load profile explicitly labels the runner preflight-only and documents missing representative workloads. These limitations are blockers, not acceptance waivers.

Additional executed checks (1200-second timeout):

- `uv run python scripts/check-deployment-claims.py`: PASS (component/backend existence only).
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `git diff --check`: PASS.

## Reachable behavior and acceptance

The schema-fence test now independently names the three audit-column upgrades
missing in the old failure (`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`).
The actual schema upgrade takes the advisory lock inside its transaction before
DDL (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`).
The fresh test pass is meaningful ordered-statement coverage, not proof of a live
concurrent PostgreSQL boot.

Production installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; the middleware creates
an `InMemoryRateLimiter` at `api/rate_limit.py:93`. The freshly executed
`tests/test_soak_promotion_gates.py:439` exercises two real middleware instances
with the same principal/client and observes `[200, 200, 429]` on each. Local
429 enforcement does not establish replica-selection non-bypass. The middleware
docstring explicitly documents N-times aggregate allowance. No alternate
authorization path or speculative distributed limiter is introduced here.

`scripts/soak/run_soak.py:1552` calls `preflight_artifact_check` (line 730),
which always returns false for the host-process topology. Executed CLI regression
tests reject even four-hour synthetic evidence with missing/null/preflight
artifact records. That protects against false promotion; it does not execute a
four-hour RC soak.

| #860 acceptance criterion | Evidence / disposition |
| --- | --- |
| Representative concurrent users/Workspaces, mix, fan-out, schedules, tasks, tools/models, Design/Canvas and workers | UNVERIFIED. `m3a-load-profile.md:151–170` explicitly records incomplete workload coverage. |
| At least two supported deployed replicas | UNVERIFIED. ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and restart | UNVERIFIED. Focused regressions do not establish sustained observations. |
| No duplicate physical work across occurrence/task/Run/Attempt/Goal paths | UNVERIFIED. Profile lines 193–203 describe the single occurrence admission probe, cancelled before physical execution. |
| Rate/security/degraded non-bypass under concurrency and replica selection | UNVERIFIED at required deployment scope; fresh middleware regression reproduces independent per-replica allowances. |
| Complete PostgreSQL, loop, worker/process, RSS, descriptor, queue and error telemetry with thresholds | UNVERIFIED for RC. Profile documents missing application-loop, worker and long-window evidence; no fresh RC series captured. |
| Active-work kill/restart proves drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection performed. |
| Long-running exact RC/config soak, repeated after runtime changes | BLOCKED / UNVERIFIED. Assignment does not designate an immutable RC/config; existing runner is explicitly incapable of certification. |
| Load findings filed/reclassified before promotion | Limitations recorded locally here; external filing UNVERIFIED. GitHub mutation prohibited and not performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for RC. Source head is identified, but historical artifacts are not recertified by these tests. |

## Disposition and handoff

**BLOCKED**, not merge-ready. Immutable RC/config designation remains
UNRESOLVED; assumption is bounded CI repair, not authority to substitute a local
checkout for the release artifact. No merge conflicts exist. No ledger changes
are warranted by the exact vulture scan. No source or test changes were made;
inventory delta is zero and no inventory note is required.

Only changed file: `docs/testing/soak/issue-860-882c69ef-repair.md`.
All inherited work is preserved. This report must be committed locally; no push
or remote mutation. The inherited branch-wide diff is not certified by these
focused checks.

Next: release owner designates immutable RC and normalized deployment config;
complete representative workload/telemetry coverage and reconcile the
replica-selection contract through canonical security before running the actual
long-duration production soak with physical-work and recovery observation.
Repeating this already-passing stale CI failure cannot satisfy those criteria.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
