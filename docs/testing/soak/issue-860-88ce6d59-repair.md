# Issue #860 — 88ce6d59 CI-repair checkpoint

## Frozen scope and assumptions

- One item: #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting head `f5ef184a7c3e341d2d858bd39f510f3396537c85`,
  base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial tree clean. No uncommitted work required salvage.
- Inputs: supplied dispatch snapshot, prior result `ff25f0aa/result.json`, and
  historical `98a11313/check-3.log`. No current-job check logs were present.
  No GitHub re-enumeration or mutations.
- Repair candidates frozen to actual vulture findings and the reported schema
  regression. Acceptance inspection: soak runner/profile/promotion tests,
  production rate middleware and registration, core fencing/recovery tests.
  This checkpoint is the only planned changed file unless execution identifies
  an actual in-scope regression. No new tests means no inventory delta.
- Writer role applies. No immutable RC or deployment configuration is selected
  in the assignment. Do not guess one or equate ASGI tests with deployed proof.
- Read repository instructions and accepted ADR-081226-a66b, ADR-085 and
  ADR-082826-08f0. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and the
  canonical recovery/authorization seams. No competing execution authority.

## Recorded results

- Exact requested vulture command passed: 1322 reviewed identities / 1322
  findings; zero unclassified or never-allowlist findings. No ledger edit is
  justified by this scan, despite permission to amend it in this lane.
- Historical check-3 expected 21 schema DDL statements, while production emitted
  24. Current test independently lists all 24, including the three validation
  audit columns. Fresh execution passes; the supplied failure is stale.
- Production `api/rate_limit.py:93` constructs an in-memory limiter per middleware
  instance; the module explicitly documents replica-local budgets.
- `scripts/soak/run_soak.py:744` rejects exact-RC equivalence for its host-process
  preflight. Duration alone cannot satisfy this gate.

## Validation and acceptance

Commands executed in the assigned worktree with 1200-second timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322/1322 reviewed identities |
| `uv sync --locked --extra dev` | PASS, 256 resolved / 214 checked |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 57 passed, 6 skipped, 1.92s |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed, 2.21s |
| `uv run python scripts/check-deployment-claims.py` | PASS; checks existence, not deployed behavior |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19 classified / 19 discovered |
| `git diff --check` | PASS |

No skipped test is counted as acceptance evidence. No test or suite-count change,
so no inventory note is required. Existing artifacts and previous reports are
not new acceptance evidence. The previous block is not a develop-sync conflict.

Production registration is reachable at `maistro_server/main.py:648`.
`tests/test_soak_promotion_gates.py:439` executes two instances of that middleware
with the same authenticated principal or pre-auth address. Both return
`[200, 200, 429]`: exhausting one replica leaves another allowance on the peer.
This is a bounded production-seam counterexample, not deployed-load evidence.
Per-principal keying under ADR-085 does not establish a shared replica budget.

The schema-fence regression at `test_pg_learnings.py:133` independently asserts
24 ordered statements inside a transaction after the advisory lock. Production
uses the lock at `pg_learnings.py:215`. Its fresh pass resolves the historical
reported failure without weakening the test or removing audit columns.

| #860 acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Read `m3a-load-profile.md`; it explicitly lacks multi-user/Workspace traffic, fan-out, successful tools/models, Design/Canvas and sustained Goal/background work. RC applicability not supplied. |
| At least two deployed replicas | UNVERIFIED. Two ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks and restart | UNVERIFIED. Executed regressions last seconds, not a long soak. |
| No duplicate physical work across schedules/tasks/Runs/Attempts/Goals | UNVERIFIED under deployed load. Fencing/recovery/admission regressions pass, but do not prove all physical-work paths. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | NOT SATISFIED at the middleware seam: same identity gets a fresh peer allowance. Other deployed security/degraded paths remain UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED. No sustained production telemetry collected. Driver-loop measurements are not application-loop measurements. |
| Active-work kill/restart proves drain/fencing/recovery | UNVERIFIED for deployed RC. Bounded canonical recovery regressions pass only. |
| Long soak of exact RC artifact/configuration, repeated after changes | UNVERIFIED. No selected immutable RC/config; runner deliberately fails artifact equivalence. Four-hour preflight tests verify rejection, not soak completion. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness without representative load. Replica-budget gap is a prerequisite rate/security issue, not throughput tuning. No issue filing permitted in this worker. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak. This source-head checkpoint is not an artifact-bound soak evidence pack. |

## Handoff

**BLOCKED.** Changed only this checkpoint. No actual vulture debt or reproducible
schema regression warrants code/ledger edits. No grants, policies, gates,
authorization paths or execution authorities changed. No GitHub mutations.

Required next inputs/work: select the immutable promotion RC and normalized
supported configuration, resolve the replica-budget prerequisite at the
canonical security seam, then run representative multi-replica load with full
telemetry and physical-work recovery observations for the required duration.
Do not treat existing host-process preflight artifacts as that evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next is the blocked exact-RC acceptance work above.
Local commit is a handoff checkpoint only, not integration approval.
