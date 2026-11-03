# Issue #860 — bounded CI repair cb14ed7a

## Frozen scope

- Only issue #860; branch `auto-860`, starting head
  `cb149d9eaeee4952e995ab1bc23a7ae18ff4d5c7`, supplied develop base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production counterpart `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` only for actually observed scanner identities,
  an inventory note if tests change, and this handoff.
- Read-only validation surfaces: existing soak scripts/tests, server rate-limit
  middleware/tests, relevant ADRs and CI gate scripts. No other issue/PR work.
- Initial worktree clean; starting ref resolved exactly. No salvage needed.

## Initial evidence and assumptions

The supplied previous check-3.log failed the schema-fence test (24 DDL calls
versus 21 expected). This is historical evidence, not proof of a current failure.
The prior result reported independent replica rate allowances and absence of
exact-RC equivalence. Both require fresh checks. The current job directory has
no check-*.log files. Interpret the assignment as writer/CI repair, not verifier.
No RC artifact/configuration is supplied; bounded tests cannot certify a long
production soak. No GitHub mutation or policy/authority changes are permitted.

## Results

Fresh required vulture scan PASSED: 1322 findings / 1322 reviewed identities,
zero unclassified and never-allowlist findings. No ledger amendment justified.
Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
-x -q`: 37 passed, 6 skipped. The current independent expected DDL list already
includes all three audit columns (lines 173–177); the supplied failure is stale.
No code repair or new test is justified by these results.

Additional fresh checks: dependency sync, repository-wide ruff lint and format
checks passed (3301 files formatted). Soak promotion gates plus server rate-limit
and task-backpressure tests: 99 passed. Canonical execution-fencing and recovery
disposition tests: 20 passed. All command timeouts were 1200 seconds.
The replica-selection test executes the real middleware with the same identity
on two instances; each independently returns [200, 200, 429]. This is a bounded
counterexample, not a deployed soak. The runner's `preflight_artifact_check`
returns false unconditionally for its host-process topology.

## Architecture reconciliation

Read accepted ADR-081226-a66b, ADR-081626-f383 and ADR-085. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt, canonical lease ownership and the
existing principal resolver. Per-principal keying does not imply shared replica
budgets; process-local enforcement is not acceptance of #860's non-bypass claim.
No competing scheduler, execution authority or authorization path was introduced.
Production installs the tested middleware at `maistro_server/main.py:648`;
`api/rate_limit.py:93` creates its instance-local limiter.

## Commands and outcomes

All executed locally, with 1200-second validation timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322/1322 |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv sync --locked --extra dev` | PASS |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run pytest packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 20 passed |
| `uv run python scripts/check-deployment-claims.py` | PASS; existence check only |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / discovered |
| `git diff --check` | PASS |

No test changes or additions; no inventory delta. Skips are not evidence of a
successful PostgreSQL integration run. No actual CI failure remains in the
supplied repair targets; changing code or the ledger would be speculative.

## Acceptance audit

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED. `m3a-load-profile.md` explicitly omits concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained Goal/background work. No selected RC establishes applicability. |
| Two deployed application replicas | UNVERIFIED. Two ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queues, reclaim, retries, memory/descriptors/process leaks | UNVERIFIED. Tests lasted seconds, not a soak. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | UNVERIFIED under load. Twenty canonical fencing/recovery tests passed; this does not establish all physical-work paths. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT SATISFIED at the tested middleware seam: `tests/test_soak_promotion_gates.py:439` proves independent allowances for both authenticated and pre-auth identities. Broader deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry with thresholds | UNVERIFIED. No production time series captured; profile distinguishes driver-loop lag from application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED for deployed RC; bounded canonical recovery checks only. |
| Long soak of exact RC/configuration, repeated after changes | UNVERIFIED. `scripts/soak/run_soak.py:744` deliberately rejects host-process artifact equivalence. No immutable RC/config supplied. |
| Load findings classified to earliest broken invariant | UNVERIFIED for completeness. Replica-budget gap belongs to prerequisite security/rate enforcement, not throughput optimization. No GitHub filing permitted. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak. This source-head validation note is not an artifact-bound soak pack. |

## Handoff

**BLOCKED** on production acceptance, not on the historical schema or vulture
checks. Changed only this report; no gate, ledger, production or test edits.
No GitHub mutations. The previous block is not a develop-sync conflict.

Next: provide the immutable promotion artifact and supported normalized runtime
configuration, resolve replica-selection enforcement at the canonical security
seam, then execute representative multi-replica sustained/recovery workloads
with full telemetry and physical-work observations. Do not re-run this same
bounded CI repair expecting it to supply missing exact-RC acceptance evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. Local commit is a handoff, not integration approval.
