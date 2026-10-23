# Issue #860 — bounded repair validation (7732978d)

## Frozen scope

- Issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `dab4550b4b7bd17fc00fd3771413030e8f4fe0c2`; clean worktree.
- Supplied comparison base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Process only supplied dispatch and prior result/check evidence, soak harness and
  adjacent tests, relevant runtime rate/task paths, relevant ADRs, CI gate scripts,
  and `quality/vulture-baseline.json` if the mandated scan identifies actual debt.
- Planned write set: this report; ledger/runtime/test changes only if current
  validation demonstrates an in-scope defect. No unrelated inherited diff changes.
- No current-job `check-*.log` files were present in the supplied job directory.
- Ambiguity: this is a writer repair assignment, not a verifier-only assignment.
  Prior BLOCKED is a claim to recheck, not permission to fabricate RC evidence.

## Results

Fresh exact vulture scan passed: 1323 findings / 1323 reviewed identities,
zero unclassified and never-allowlist findings (scanner base `3c761d14db94`).
No ledger amendment is warranted by this scan.

Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
-x -q`: 37 passed, 6 skipped. Supplied historical `98a11313/check-3.log`
reported a 24-versus-21 schema assertion; that failure does not reproduce.

Read the captured #860 acceptance body, existing promotion tests and profile.
The current profile explicitly identifies its host-process topology and missing
representative workload/telemetry as non-promotion evidence. No production evidence or promotion approval claimed.

## Additional executed validation

All commands below completed successfully:

- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 1 passed.
- `uv run python scripts/check-backlog-consistency.py`: 168 items validated.
- `uv run python scripts/check-deployment-claims.py`: named components exist;
  this static gate does not prove deployment or soak behavior.
- `uv run python scripts/check-execution-lifecycles.py`: 19 classified /
  19 discovered, unchanged.

Exact vulture command executed:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
This matches the CI command in `.github/workflows/vulture-ratchet.yml:82`.
The historical schema expectation now includes all three Gauntlet audit columns
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`.
Six PostgreSQL-dependent tests skipped; no live database validation claimed.

## Architecture and production-path audit

Read repository instructions, documentation authority hierarchy, accepted
ADR-085, ADR-081226-a66b and ADR-081626-f383, and proposed ADR-081.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt: admission uniqueness
is not proof of physical Attempt fencing. Proposed deployment text cannot
waive acceptance, and no new scheduler, store, authorization or execution
owner was introduced.

`packages/maistro-server/src/maistro_server/main.py:648` installs the rate
middleware. Its constructor at `api/rate_limit.py:90–98` creates an independent
InMemoryRateLimiter. The executed test at `tests/test_soak_promotion_gates.py:439`
uses this production middleware and observes [200, 200, 429] on each instance
for the same identity, for both authenticated and unauthenticated traffic.
This falsifies shared-budget enforcement but is not deployed-RC security proof.
ADR-085's principal identity contract is not permission to invent a new
cluster authority: `BACKLOG.md:267–279` records engine-116 as an outstanding
cluster-budget specification decision. No speculative shared-store repair.

The backpressure test uses the real router, TaskQueue and canonical admission
spine: fills two slots, gets 429 with Retry-After, admits another principal,
then admits the original principal after terminalization. This proves a local
HTTP contract, not multi-replica physical execution.

## Acceptance audit

| #860 criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC load profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` explicitly omits multi-user/Workspace populations, Graph fan-out, successful tool/model work, Design/Canvas and Goal/background activity. No selected RC configuration justifies excluding them. |
| At least two deployed application replicas | UNVERIFIED. ASGI middleware instances are not deployed RC replicas; no production soak run here. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. Focused tests do not establish long-window behavior. |
| No duplicate physical work; Goal reconciliation | UNVERIFIED. `scripts/soak/run_soak.py:1067–1092` cancels a queued schedule admission probe without executing its physical work. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | Negative evidence: executed middleware test demonstrates independent allowances. Deployed security/degraded behavior remains UNVERIFIED. |
| Required telemetry with explicit thresholds | UNVERIFIED. Profile distinguishes driver loop lag from application lag and lacks promotion-grade worker/pool/lease/leak observations. No fresh deployed telemetry captured. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED. No active physical Attempt restart experiment executed. |
| Long exact-RC artifact/configuration soak | UNVERIFIED. `scripts/soak/run_soak.py:744–755` unconditionally rejects its host preflight as exact RC; executed CLI tests reject even four-hour synthetic preflight evidence. No immutable promotion image/config supplied or exercised. |
| Classify findings before promotion | Partial: engine-116 documents the rate-budget gap; backlog gate passes. Completeness for a new RC soak is UNVERIFIED. No GitHub mutation. |
| Publish hash-bound machine/human soak evidence | UNVERIFIED. This report records local checks, not a hash-bound production evidence pack. |

## Disposition and next action

BLOCKED for #860 acceptance. The supplied CI failure does not reproduce and
vulture has zero unbanked identities, so no code/test/ledger repair is justified.
Only this report changes; test inventory delta is zero (no test additions).
Inherited branch changes are preserved; the large supplied-base comparison was
not treated as permission to rewrite unrelated work. No merge conflicts exist.

Next requires an explicitly designated immutable RC image and runtime config,
a resolved cluster-budget contract, representative traffic and telemetry,
and the profile's at-least-four-hour exact-artifact soak including active
Attempt restart/fencing/recovery. Repeating this stale CI repair cannot replace
those inputs. No full-tree pytest, live production load, GitHub mutations,
quality-gate weakening or promotion approval.

Progress: checked 1 issue; done 1 local validation/handoff; skipped 0 issues;
errors 0 validation commands. Full acceptance remains blocked. This local
commit is a handoff, not integration approval.
