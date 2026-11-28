# Issue #860 — ff25f0aa repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `cedc622c591239f7a742e9df41e310b67782cd1f`, assigned base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree clean; no salvage patch needed.
- Review the supplied dispatch snapshot and prior failed check; no GitHub mutations
  or fresh issue/PR enumeration.
- Repair target: `quality/vulture-baseline.json` only for actual reviewed scanner
  findings, or genuinely dead source identified by that scan. Acceptance review:
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, production
  rate-limit middleware and adjacent tests, load-profile/evidence documents and
  relevant ADRs. This note records results. Do not broaden into a new distributed
  scheduler or admission authority.
- Current job directory contained no `check-*.log` on initial inspection.
- Prior result reports BLOCKED (missing deployed exact-RC evidence and replica-local
  rate limiting); these claims require independent validation.

## Progress

- Exact requested vulture scan passed: 1322 findings / 1322 reviewed identities,
  zero unclassified or forbidden findings. No ledger amendment is warranted.
- `uv sync --locked --extra dev` passed (256 resolved, 214 checked).
- Supplied historical `98a11313/check-3.log` failed because the schema-fence test
  expected 21 DDL statements instead of 24. Current test already includes the
  three audit columns; fresh execution passes. The supplied failure is stale.
- Read the snapshot's ten acceptance criteria and accepted ADR-081226-a66b,
  ADR-085 and ADR-082826-08f0. Canonical lifecycle and proven-liveness recovery
  remain authoritative. Per-principal keying is not evidence of shared budgets.
- Assumption: writer role applies. No immutable promotion RC/configuration is
  identified in the assignment; do not guess one or relabel host-process tests
  as exact-artifact deployment proof.

## Executed validation

Commands ran in the assigned worktree with 1000/1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322 reviewed / 1322 findings, base `321cbdb8fe9b` |
| `uv sync --locked --extra dev` | PASS |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3301 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 57 passed, 6 skipped, 1.94 seconds |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed, 2.19 seconds |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence only, not deployment proof |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / 19 discovered |
| `git diff --check` | PASS |

No test additions/changes or suite-count changes; no inventory note required.
No unbanked or removed vulture identities exist to amend. Changing the ledger
merely because the lane permits it would not repair an actual failure.

## Reachable behavior and acceptance

Production installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`. Its constructor at
`api/rate_limit.py:93` creates a separate in-memory allowance. Executed
`tests/test_soak_promotion_gates.py:439` tests the same authenticated principal
and the same pre-auth address against two middleware instances: each returns
`[200, 200, 429]`. Exhausting replica one does not exhaust replica two. This is
bounded evidence of the production middleware behavior, not deployed traffic.

`scripts/soak/run_soak.py:744` explicitly returns `ok: false` for exact-RC
artifact equivalence. The executed four-hour-preflight CLI regressions prove
this gate fails closed. Extending its duration cannot establish production
Compose image/configuration equivalence. The profile itself identifies the
remaining workload and telemetry gaps; they are not acceptance waivers.

The schema-fence test at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:133` independently
asserts all 24 ordered DDL statements inside one transaction, after the advisory
lock. The production transaction/lock is at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`. Its passing
execution resolves the historical reported check failure without another edit.

| Issue acceptance criterion | Fresh evidence and verdict |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md` supplies a preflight mix but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background work. Selected-RC applicability is not supplied. |
| At least two deployed application replicas | UNVERIFIED. Two real middleware instances were exercised in ASGI, not two deployed RC images. |
| Sustained saturation, growth, reclaim, retries, leaks and restart | UNVERIFIED. Tests above are bounded seconds-long regressions, not a long soak. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED under deployed load. Fencing/recovery/admission regressions pass, but admission uniqueness and stale-write fencing alone cannot prove physical-work uniqueness. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | NOT SATISFIED at the production middleware seam: identical identity receives another allowance on replica two. Security/degraded behavior under representative deployed concurrency remains UNVERIFIED. |
| Complete PostgreSQL, application loop, workers/processes, RSS/fds, queue and error telemetry with thresholds | UNVERIFIED. Sampler regression passes, but this run produced no sustained production telemetry. Driver loop latency is not application loop latency. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED for the deployed RC. Canonical recovery regressions pass at bounded scope only. |
| Long exact-RC artifact/configuration soak, repeated after changes | UNVERIFIED. No immutable RC/configuration selected; available runner deliberately rejects equivalence. Profile minimum is four hours. |
| Findings classified at earliest broken invariant | UNVERIFIED for completeness without representative load. Replica-budget gap belongs to prerequisite rate/security enforcement, not throughput tuning. Recorded locally; no GitHub mutation. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for production soak. This source-head validation report is not an exact-artifact evidence pack. |

## Final handoff

**BLOCKED.** Only this evidence/checkpoint document changes. No source, tests,
ledger, grant, or gate change is justified by the fresh CI results. The previous
block is not a merge conflict and remains a production-evidence/prerequisite
block, not a scanner repair. Do not invent a distributed limiter or alternate
execution authority inside a bounded soak CI-repair round.

Next action requires an explicitly selected immutable RC and normalized supported
deployment configuration, resolution of the replica-budget prerequisite through
the canonical security seam, and a representative exact-artifact soak with full
telemetry and physical-work recovery observations. Do not promote the preflight
artifacts or these regressions as that evidence.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
validation errors 0. Local commit is a handoff checkpoint only. No GitHub
mutations or changes outside the assigned worktree.

