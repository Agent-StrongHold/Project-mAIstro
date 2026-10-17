# Issue #860 — repair validation (59ddd9df)

## Frozen scope and initial evidence

- Only issue #860, worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `3453e5dfea5f053a5f882b07ff170127bd548e3e`; worktree clean.
- Supplied base: `2154f845347c9541016288c760f8da3f5cd2e064` resolves.
- Read set: supplied dispatch and prior result/check logs, repository instructions,
  relevant execution/security/deployment ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, load profile, production rate middleware,
  schema-fence and task-backpressure tests, and relevant CI gate definitions.
- Planned write set: this report; `quality/vulture-baseline.json` and implicated
  runtime/test files only if current validation demonstrates an actual defect.
- No current-job `check-*.log` files present. Supplied historical `check-3.log`
  is a schema test failure (24 DDL statements versus 21 expected), not a vulture
  failure. Previous BLOCKED disposition is not fresh acceptance evidence.
- Ambiguity resolved: writer repair assignment takes precedence over generic
  verifier wording. No selected immutable RC/deployment configuration supplied.
- Large inherited base diff is preserved, not permission to repair other issues.

## Validation

- Exact requested vulture command passed: 1323 findings / 1323 reviewed
  identities, zero unclassified or never-allowlist findings. No justified ledger
  amendment; existing multiset remains unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical schema assertion failure does not reproduce.
- Captured issue body contains ten acceptance criteria; each will be accounted
  for below. No production soak or promotion claim.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed (72 promotion/probe tests, 1 task backpressure test).
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run python scripts/check-deployment-claims.py`: passed (static existence,
  not evidence of a deployed topology).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified
  and 19 discovered lifecycles.

The vulture command was
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
matching `.github/workflows/vulture-ratchet.yml:82`. Scanner comparison base was
`3c761d14db94`; this is not the supplied comparison base. No gates were changed.
The schema expectation already includes the three Gauntlet audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`.
Six database-dependent tests skipped; no live PostgreSQL result claimed.

## Architecture and acceptance evidence

Read repository instructions, docs authority map, accepted ADR-085,
ADR-081226-a66b, ADR-081626-f383, and proposed ADR-081. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. Admission uniqueness cannot be
substituted for physical Attempt fencing. The accepted lease ADR explicitly
leaves expiry takeover/recovery supersession to a later contract: do not invent
reclaim authority merely to satisfy the issue. Proposed deployment text does
not waive acceptance. No competing scheduler, store, authorization, event or
execution owner was added.

The production app installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates
an independent in-memory limiter at `api/rate_limit.py:90–98`. The executed test
`tests/test_soak_promotion_gates.py:439` observes [200, 200, 429] on each of two
instances for the same identity (authenticated and unauthenticated). This is
negative evidence for replica-selection non-bypass, not a deployed security
soak. `BACKLOG.md:267–279` records engine-116 as the outstanding cluster-budget
specification decision. No speculative coordination service was introduced.

| #860 acceptance criterion | Fresh evidence / limitation |
|---|---|
| Representative RC workload | UNVERIFIED. Profile's remaining-gaps section omits concurrent users/Workspaces, Graph fan-out, successful tool/model work, Design/Canvas and Goal/background reconciliation. No selected RC configuration justifies exclusions. |
| At least two deployed application replicas | UNVERIFIED. Executed ASGI tests instantiate middleware, not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. Local tests have no sustained production window. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED. `scripts/soak/run_soak.py:1067–1092` cancels the queued admission probe without executing it. Task backpressure test proves HTTP admission behavior only. |
| Replica-selection non-bypass for rate/security/degraded behavior | Negative evidence: independent allowances reproduced by production middleware test above. Deployed security and degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED. Profile distinguishes driver loop lag from application lag and acknowledges missing promotion-grade pool/worker/lease/leak observations. No fresh deployment telemetry collected. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED. No active physical Attempt restart experiment executed. |
| Long exact-RC artifact/config soak | UNVERIFIED. `scripts/soak/run_soak.py:744–755` always rejects host preflight as exact RC. Executed CLI test at `tests/test_soak_promotion_gates.py:103` rejects even four-hour synthetic preflight evidence. No immutable promotion artifact/config supplied or exercised. |
| Findings classified before promotion | Partial: engine-116 is recorded and backlog gate passes. Classification completeness for an actual RC soak UNVERIFIED. No GitHub mutations. |
| Machine/human evidence bound to exact hashes | UNVERIFIED. This local validation report is not a production evidence pack. |

## Disposition and handoff

BLOCKED for issue acceptance. The reported CI failure does not reproduce and
the mandated scan identifies no debt requiring amendment. Only this report
changes; no new tests, so inventory delta is zero and no inventory note needed.
All inherited work is preserved. No merge conflicts or sync-conflict evidence
were present; no fetch/merge was necessary for this bounded repair.

Next: designate the immutable RC image/configuration, resolve the cluster-budget
contract, complete representative workload/telemetry, and execute the profile's
at-least-four-hour exact-artifact soak with active Attempt restart/fencing/recovery.
Repeating this stale CI repair cannot supply those missing inputs. Full-tree
pytest and production load were not run; no promotion or integration approval.

Progress: checked 1 issue, done 1 local validation/handoff, skipped 0 issues,
errors 0 validation commands. Acceptance remains blocked; local commit is a
handoff only.
