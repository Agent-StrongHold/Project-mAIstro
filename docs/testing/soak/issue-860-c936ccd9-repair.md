# Issue #860 — bounded CI repair c936ccd9

## Frozen scope

- Only issue #860; branch `auto-860` in the assigned worktree.
- Starting HEAD: `f98c9d3a7d5b7fa3ec23a963f7ea3cb2490b1a95`.
- Supplied base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Initial working tree clean; no incoming edits to salvage.
- Snapshot: supplied `dispatch-context.json`; no GitHub queries or mutations.
- Repair targets: observed vulture identities and their source definitions, if any;
  existing soak runner/tests for focused validation; this evidence note.
- Ledger changes permitted only for reviewed identities reported by the exact gate.

## Initial evidence and ambiguity

The current job directory contains no driver `check-*.log` files. The supplied
prior result reports BLOCKED, not release evidence. Assumption: reproduce the
specified exact vulture command and independently validate reachable soak tests;
never infer an exact-RC multi-replica soak from unit tests. Production deployment
and the exact promotion artifact/configuration are not supplied by this job.

## Fresh validation

All commands ran in the assigned worktree with 600–1,200 second timeouts.
Logs are in `/home/dev/maistro/jobs/c936ccd9db084b74a5ae144fd545cb45/`.

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,322 reviewed identities / 1,322 findings; zero unclassified or never-allowlist findings | `check-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped | `check-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed | `check-soak-tests.log` |
| `uv run ruff check .` | PASS | `check-ruff.log` |
| `uv run ruff format --check .` | PASS: 3,301 files already formatted | `check-format.log` |

The vulture command chose base `321cbdb8fe9b`, as printed by its ratchet;
this is not the supplied campaign base. No flags, ledger, or grants were
changed to influence the result. There are no reported identities to amend.

Read the historical `98a11313167b41a98a420abfda80c292/check-3.log`:
it expected 21 DDL statements but observed 24. The current schema test already
asserts the three validation-audit columns independently of production constants
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:176`). Its fresh
pass resolves that historical validation failure without a new code edit.
Skipped database cases do not establish live PostgreSQL behavior.

## Architecture and reachable behavior

Read repository `AGENTS.md`, documentation authority hierarchy, accepted
ADRs `081426-1f7c` (ExecutionRuntime) and `081626-f383` (execution fencing),
the existing load profile, runner gate, production task routes/rate middleware,
and adjacent regression tests. No competing execution or authorization path
was introduced; Goal -> Graph -> Run -> NodeRun -> Attempt remains canonical.

The fencing ADR explicitly does not define lease-expiry takeover or recovery
supersession of live Attempts. Reconciliation: the issue's reclaim criterion
remains a dependency, not permission for this lane to invent reclaim authority.

- `scripts/soak/run_soak.py:744`: `preflight_artifact_check` unconditionally
  reports `ok: false`; host uvicorn processes are not the promoted Compose
  artifact. Longer preflight execution cannot fix artifact equivalence.
- `tests/test_soak_promotion_gates.py:439`: executed test uses real production
  middleware and the same identity on two instances; each independently returns
  `[200, 200, 429]`. This verifies local enforcement but falsifies a shared
  aggregate allowance. It agrees with the explicit process-local contract in
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`.
- `tests/test_soak_promotion_gates.py:564`: executed test uses the real task
  router and a shared canonical admission spine; an admitted receipt returns
  200 locally and 404 on the peer. `api/tasks.py:146` reads the local queue.
- The server backpressure test passes with real canonical admission, principal
  isolation, 429/Retry-After at capacity, and subsequent admission after release.
  It deliberately starts no runner; it cannot prove physical-work recovery.

## Acceptance assessment

| # | Criterion | Evidence and status |
| --- | --- | --- |
| 1 | Representative RC workload | UNVERIFIED: inspected profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/worker coverage |
| 2 | At least two deployed application replicas | UNVERIFIED: executed ASGI seam tests, not a deployed production soak |
| 3 | Sustained saturation, queues, reclaim, retries and leaks | UNVERIFIED: no sustained run; reclaim authority also unresolved by the accepted ADR |
| 4 | No duplicate physical work including reconciliation | UNVERIFIED: admission tests do not prove physical Attempt or Goal reconciliation behavior under load |
| 5 | Replica-resistant security/degraded behavior | UNVERIFIED overall: local rate allowances multiply across instances; admission backpressure passes |
| 6 | Production telemetry and explicit thresholds | UNVERIFIED: inspected profile thresholds, but no fresh production pool/lock/loop/worker/RSS/descriptor/error series |
| 7 | Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no active-work restart experiment |
| 8 | Long soak of exact immutable RC/configuration | UNVERIFIED: no selected immutable RC supplied and runner explicitly rejects equivalence |
| 9 | Findings classified to earliest broken milestone | UNVERIFIED for completeness: no completed load run; local blockers recorded without prohibited GitHub mutations |
| 10 | Machine/human soak evidence tied to artifact/config hashes | UNVERIFIED for promotion: these logs and report establish local validation only |

## Handoff

**BLOCKED**, not integration approval. Only this report changed. No source,
tests, gates, ledger or grants changed; no suite-count delta or inventory note
is required. Prior implementation and evidence are preserved. An immutable RC
selection, complete production-profile workload and resolution of canonical
reclaim/replica-budget dependencies are needed before the long production soak.
Repeating the same vulture repair cannot resolve those acceptance dependencies.

Progress: checked 1 issue; done 0 acceptance sets; skipped 0 issues; errors 0
validation commands. Next: supply the exact RC deployment/configuration and
resolve the listed production acceptance blockers. This report is committed
locally; no push or GitHub mutation performed.
