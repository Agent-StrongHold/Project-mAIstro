# Issue #860 repair checkpoint — 70593f5c

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`18ac43fe6b593b5d27a64405edcfe3fff4bbe5d9`, base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
No GitHub mutations or develop merge required (no conflict present).

Repair candidates frozen to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
its production module `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`quality/vulture-baseline.json` only if the mandated scan supplies actual evidence,
an inventory note if tests change, and this checkpoint. Acceptance review is
limited to the existing soak profile/runner/tests and relevant ADRs.

The supplied old check-3.log reports 24 schema statements versus 21 expected.
That is historical evidence, not yet a reproduced failure. The current job
contains no check-*.log files. Prior result reports BLOCKED, not a merge conflict.
Assumption: validate the existing fixes before making further changes; do not
invent an RC artifact/configuration or substitute smoke tests for a long soak.

## Results

- Exact mandated vulture scan: PASS, 1,322 findings / 1,322 reviewed identities;
  zero unclassified and never-allowlist findings. Selected gate base
  `321cbdb8fe9b`; candidate `18ac43fe6b59`. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped in 1.33s. Historical check-3 failure does not
  reproduce: lines 176–180 already cover the three added audit columns.
  Skipped PostgreSQL cases do not prove live database concurrency.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 73 passed in 2.12s. Combined with the persistence command: 110 passed,
  6 skipped. Commands used 1,200-second timeouts.
- Reviewed `.github/workflows/quality.yml:1079`: mandated vulture invocation
  matches CI exactly. No test changes, so no inventory delta is required.

## Production-path findings and ADR reconciliation

Read repository instructions, docs authority hierarchy, the complete load
profile, and accepted ADRs `081426-1f7c` and `081626-f383`.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt model is unchanged.
The fencing ADR deliberately excludes live-Attempt lease-expiry takeover;
#860 does not authorize inventing another reclaim authority to pass a soak.

Freshly executed tests use the actual production rate middleware and task
router, but ASGI clients rather than deployed replicas:

- `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` separately
  on both middleware instances for the same IP/credential. This agrees with
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`: the
  documented budget is per process, not cluster-wide. Local enforcement is
  not proof of the issue's replica-selection criterion.
- `tests/test_soak_promotion_gates.py:564` observes local receipt 200 and peer
  receipt 404 using the production task router. Its handler at
  `packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the queue.
- `scripts/soak/run_soak.py:744` explicitly returns `ok=False` for exact-RC
  artifact equivalence. The current runner is a host-process preflight, not
  the promoted Compose configuration. Increasing its duration cannot fix that.

## Acceptance review

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC profile | UNVERIFIED: reviewed profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker coverage; no selected RC configuration supplied to justify omissions. |
| Two deployed application replicas | UNVERIFIED: two ASGI instances are not deployed production replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | UNVERIFIED: short targeted tests; no production time series or reclaim experiment. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED: admission and receipt tests do not execute physical Attempts or sustained Goal reconciliation. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall: fresh production-middleware tests demonstrate additional allowance from replica selection; local task backpressure tests pass. |
| PostgreSQL/loop/worker/RSS/descriptors/queue/error telemetry with thresholds | UNVERIFIED: profile defines thresholds, but no fresh production measurements; driver-loop lag does not establish application-loop lag. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no physical worker or active-work restart was exercised. |
| Long exact-RC soak | UNVERIFIED: no immutable RC/configuration supplied; runner explicitly rejects equivalence. |
| Classify load findings to earliest broken milestone | UNVERIFIED for completeness: no completed production run; blockers recorded locally, no GitHub mutations. |
| Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED for promotion: this record identifies the checked commit, not an executed production image/configuration soak. |

## Handoff

**BLOCKED**, not merge-ready. Only this validation record changed. No source,
test, inventory, gate, ledger or grant changes were justified by the fresh
checks. Historical check-3 failure is already resolved; vulture repair is not
needed. Do not dispatch another identical ledger-repair round for these gaps.
Next requires a selected immutable RC/configuration, representative production
workload and exact-artifact runner, and resolution/reconciliation of the
replica-budget, receipt and reclaim limitations before the long production soak.

Progress: checked 1 issue, done 0 acceptance sets, skipped 0 issues, errors 0
validation commands. All existing work preserved. Commit locally only; this is
not integration approval or an issue-closure action.
