# Issue #860 repair — job 6a44e5a3

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `e85625a34dfd41b0b581aad76c15bf18850d7282`, supplied base
  `2154f845347c9541016288c760f8da3f5cd2e064` (both resolved locally).
- Starting worktree clean; no incoming changes to salvage.
- Inspect the supplied dispatch snapshot, prior result and check logs; no remote
  mutation or re-enumeration of issues/PRs.
- Repair surface: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and `quality/vulture-baseline.json` only
  if actual reproduced findings require a change; supporting soak profile,
  production call sites, ADRs, and adjacent tests are read/validation inputs.
- Any added tests require a matching inventory note. No new scheduler, execution
  authority, event authority, authorization path, or quality grant.

## Initial evidence and assumptions

The current job directory contains no `check-*.log` files. The explicitly supplied
prior job has four such logs; inspect those rather than assume they remain valid.
The previous result says BLOCKED on production-soak evidence, not a merge conflict;
therefore no develop merge is assumed necessary. This round will independently
run the prescribed vulture gate and bounded acceptance checks. A passing unit
suite cannot certify a long-running exact-RC soak.

## Validation and disposition

The prescribed vulture command passed: 1323 findings / 1323 reviewed identities,
zero unclassified and never-allowlist findings. No ledger amendment is justified.
The historical `check-3.log` instead fails the learning-schema assertion (24
statements versus 21 expected). The starting tree already lists the three
Gauntlet audit columns independently at `test_pg_learnings.py:175–177`.
Fresh focused validation passed (130 passed, 6 skipped in 2.88 s), including
that schema regression and the production-middleware independent-allowance
reproduction. No production repair has been demonstrated necessary for the
reported CI failure. Skips are not live database acceptance evidence.

All four supplied historical logs were inspected. Logs 0–2 record successful
sync/lint/format; log 3 records the now-nonreproducing schema assertion. The current
round independently executed the following (600/1200-second command timeouts):

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS; 256 resolved, 214 checked |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323, exact `.github/workflows/quality.yml:1078` invocation |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | PASS; 130 passed, 6 skipped, 2.88 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run python scripts/check-deployment-claims.py` | PASS; static existence only, not deployment proof |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / 19 discovered |

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, and ADR-081626-f383, ADR-085,
ADR-082526-b36a, ADR-082826-08f0, and ADR-081. ADR-081 is **Proposed**, not an
accepted authority despite its references in the profile/Compose comments.
The accepted renewal and recovery ADRs extend the original lease boundary:
recovery refuses live ownership and reclaims expired leases through the canonical
lifecycle seam. Fencing a stale write is not proof against duplicate physical
execution. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical
authorization/events; no alternative mechanism was introduced.

The shipping reference `deploy/docker-compose.prod.yml` has two application
replicas, primary/replica PostgreSQL, Redis and a shared store, with required model
gateway configuration. The inspected host-uvicorn preflight is not this artifact.
ADR-085's principal identity rule does not itself supply a cluster-coordinated
limiter. Existing production middleware explicitly has process-local semantics;
accepting that implementation contract does not waive #860's replica-selection
acceptance criterion.

## Acceptance disposition (all ten criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Read `docs/testing/soak/m3a-load-profile.md`; its remaining-gaps section excludes concurrent users/Workspaces, Graph fan-out, successful model/tool work, Design/Canvas and Goal/background reconciliation. Applicability to the promoted configuration is not established. |
| At least two deployed application replicas | UNVERIFIED. Reference Compose declares two; fresh ASGI tests instantiate two middleware instances, not two deployed RC images. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and shutdown | UNVERIFIED. The executed tests last seconds; no sustained production observation was executed. |
| No duplicate schedule/task/Run/Attempt physical work or Goal reconciliation | UNVERIFIED under load. Bounded execution-fencing/recovery tests pass; observed admission identity alone cannot prove unique physical work. Profile phase 4 races one occurrence and cancels its queued Run without executing it. |
| Rate limiting/security/degradation not bypassable by replica selection | NOT SATISFIED at the tested middleware seam. `tests/test_soak_promotion_gates.py:439` freshly observes `[200, 200, 429]` on each instance for the same identity, both authenticated and unauthenticated. `rate_limit.py:93` constructs a local limiter; production `main.py:648` installs it. Full deployed security/degradation remains UNVERIFIED. |
| Required telemetry with explicit thresholds | UNVERIFIED. No fresh production series for all required PostgreSQL, application-loop, worker/process, RSS/descriptor, queue/error/timeout metrics. The profile's driver-loop metric is not application-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED under deployed sustained traffic. Passing bounded recovery-disposition tests are not this experiment. |
| Long soak of exact RC, repeated after code/config changes | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly returns `exact_rc_artifact.ok=false`; executed CLI regressions at `tests/test_soak_promotion_gates.py:103` reject synthetic four-hour preflight evidence. No exact-RC deployment was executed in this round. |
| Findings classified to earliest broken invariant | PARTIAL; `BACKLOG.md:267` tracks the cluster-budget gap (engine-116). Completeness UNVERIFIED without the requested sustained investigation. No GitHub mutations. |
| Human/machine evidence tied to exact image/package/commit/config hashes | UNVERIFIED. This source-head validation report is not a hash-bound exact-RC soak evidence pack. |

## Handoff

**BLOCKED** on #860 acceptance, not on the reported historical CI failure.
No evidence-supported vulture or production code change was found in this repair
scope. Only this handoff report changed; no tests added, no inventory delta,
no ledger/grant edits and no remote mutation. Local commit is a checkpoint, not
integration approval.

Next requires an explicitly designated immutable RC image/configuration and
applicable workload, closure of the cluster-budget prerequisite through existing
identity/limiter seams, then at least four hours of exact-RC measurements including
active-work failure/recovery and physical-work uniqueness. Repeating the same
passing CI command or extending this host preflight cannot resolve that blocker.
Do not dispatch another identical ledger repair without a fresh failing gate or
new RC/workload inputs.

Progress: checked 1 issue, acceptance-complete 0, skipped 0, validation errors 0;
next: production-soak prerequisites and execution. The previous BLOCKED outcome
is independently confirmed, not resolved.
