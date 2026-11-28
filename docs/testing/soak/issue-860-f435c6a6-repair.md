# Issue #860 repair — f435c6a6

## Frozen scope

One item: issue #860 at starting HEAD `5ee6cedc018e6e3af2889df6182d78df859b3268`,
base `3c761d14db944a727fa0744444bc67cfe36d49f7`, worktree `auto-860`.
No PRs or other issues will be processed. Initial worktree clean.

Candidate write files: this report; `packages/maistro-core/tests/persistence/test_pg_learnings.py`
if the supplied failure reproduces; `packages/maistro-core/src/maistro/persistence/pg_learnings.py`
only if production fencing is broken; `quality/vulture-baseline.json` only for
actual reviewed scanner findings under the explicit CI-repair exception;
`docs/testing/inventory-notes/860-f435c6a6-repair.md` if tests change.
Read-only acceptance inspection: `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, existing soak profile/evidence, production
rate-limit wiring, relevant ADRs and CI gate instructions.

## Initial evidence and assumptions

The current job directory contains no `check-*.log` files. Supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports a schema-fence test
expecting 21 statements while production executed 24. This is historical,
not assumed current. Prior result reports BLOCKED on exact-RC evidence and
replica-local rate limiting. Revalidate rather than accept those claims.
No unresolved refs or merge conflict; no develop merge indicated.

## Validation

- Required exact vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlist findings. No ledger edit justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce: the current
  assertion independently includes all 24 statements including the three
  Gauntlet audit columns. PostgreSQL integration cases skipped.

Schema-fence/ledger repair item checked: no current defect demonstrated;
continue only the assigned acceptance validation, not speculative code changes.

- `uv sync --locked --extra dev`: PASS, 256 resolved / 214 checked.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  66 passed. Includes real middleware instances, real child-process resource
  sampling, fail-closed artifact gates, and canonical task-route backpressure.
- `uv run python -` importing `scripts/soak/run_soak.py` and evaluating retained
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`: assertions PASS;
  failed promotion checks are `sustain_duration` and `exact_rc_artifact`.
  Duration 420.09 seconds versus 14400 minimum. Current
  `preflight_artifact_check()` returns `ok=false`, host-uvicorn-preflight.
- Vulture invocation matches `.github/workflows/quality.yml:1078` and
  `vulture-ratchet.yml:82`. No tests changed, so no suite inventory delta.

## Architecture reconciliation

Read accepted ADR-085, ADR-081626-f383, ADR-082526-b36a and ADR-082126-f69c.
Keep `Goal -> Graph -> Run -> NodeRun -> Attempt`; recurrence produces canonical
Runs and lease renewal/reclaim belongs to canonical execution, not a soak-owned
scheduler or authority. The later lease ADR extends the earlier fencing
contract: missing soak proof is not evidence that reclamation lacks a contract.
ADR-085 requires principal-keyed enforcement. The process-local implementation
and its documented N-times aggregate budget do not establish #860's stronger
replica-selection non-bypass criterion. No policy exception is invented here.

## Acceptance review (all ten criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** Inspected `m3a-load-profile.md` and `run_soak.py:1373`: one credential and five request classes, without representative concurrent Workspaces, Graph fan-out, successful model/tool calls, Canvas or Goal/background work. |
| Two deployed application replicas | **UNVERIFIED for RC.** Middleware tests execute two independent instances, not two immutable deployed RC replicas. Current artifact check explicitly identifies host preflight. |
| Sustained saturation, reclaim, backoff and leaks | **UNVERIFIED.** Executed evaluator rejects retained 420.09-second evidence; sampler tests demonstrate observation mechanics, not sustained production load. |
| Physical-work uniqueness across schedules/task/Run/Attempt/Goal | **UNVERIFIED.** Admission receipt tests do not establish unique physical effects. The documented schedule probe cancels its queued Run without executing it; no new sustained physical-effect accounting was run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Contrary evidence reproduced.** `tests/test_soak_promotion_gates.py:439` executes real production middleware for authenticated and unauthenticated identities. Exhausting replica one yields `[200,200,429]`, then the same identity gets `[200,200,429]` on replica two. Wiring is reachable at `maistro_server/main.py:648`; independent limiter construction is `api/rate_limit.py:93`. Task-route 429/Retry-After and subsequent re-admission tests pass, but full RC security/degraded acceptance is **UNVERIFIED**. |
| Complete telemetry and thresholds | **UNVERIFIED under RC load.** Real child RSS/descriptor tests pass; `run_soak.py:1410` measures driver loop lag, not application event-loop latency. No complete production series was captured here. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** Inspected process-group signal/rejoin code at `run_soak.py:1427`; rejoin and terminal counts alone do not prove physical-effect recovery. No new active-work deployment test executed. |
| Long exact-RC artifact/config soak | **BLOCKED / UNVERIFIED.** Executed evaluator rejects both duration and artifact; `run_soak.py:730` intentionally refuses host-preflight equivalence. This dispatch supplies source refs, not a selected immutable promotion image/configuration. |
| Findings filed/reclassified before promotion | **UNVERIFIED.** Historical finding records are not proof of current external disposition. No GitHub mutations performed. |
| Machine/human evidence bound to exact promotion hashes | **UNVERIFIED for RC.** Retained JSON fails current promotion checks. This report is focused validation evidence, not a replacement soak or promotion approval. |

## Handoff

Only this report changed. No production/test/ledger edits were warranted by the
fresh deterministic checks; the supplied CI failure is stale. No prior work or
evidence discarded, no gates weakened, no GitHub mutation.

**BLOCKED.** Required next work: identify the immutable RC/configuration, resolve
replica-budget semantics, and run a representative production-path long soak
with physical-work/recovery accounting and complete telemetry. Do not repeat
the stale schema/vulture repair dispatch as if it could close these gaps.
PostgreSQL integration tests remain skipped and are a residual validation risk.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC soak and replica-budget resolution"}`.
Local report commit is handoff only, never integration approval.
