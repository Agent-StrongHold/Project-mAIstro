# Issue #860 — repair checkpoint (382c5f39)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`85df95356e74a1424c9ac03e535c3c7c589e0e85`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Worktree was clean. No salvage was required. No check-*.log files were present
in the supplied job directory at initial inspection.

Planned write scope: this report and `quality/vulture-baseline.json` only if
actual scan evidence warrants the explicitly authorized ledger repair.
Read scope: supplied dispatch/result/log evidence, repository instructions,
relevant ADRs, vulture checker/workflow, existing soak harness/profile/tests,
and production code referenced by those tests. No other issues or PRs will be
processed; no GitHub mutation or remote refresh.

Assumption: this is a writer CI-repair round, not a verifier-only round.
Prior BLOCKED claims are not acceptance evidence; rerun focused validation.
The large inherited branch diff is preserved, not rewritten.

## Results

- Executed the prescribed vulture command with CI scan arguments; exit 0.
  Raw output: `/tmp/860-382c5f39-vulture.log`. No speculative ledger edits.
- Read the primary issue body from the frozen dispatch: ten acceptance criteria
  require representative, exact-RC production evidence, not merely passing tests.
- Focused pytest (schema fence, task backpressure, soak promotion gates,
  production-stack boot contract), full-tree ruff check and format check all
  returned exit 0. Logs: `/tmp/860-382c5f39-{pytest,ruff,format}.log`.
- Read the cited prior check-3 failure: expected 21 schema statements but saw 24.
  That failure does not reproduce in the focused current-head run.
- Inspected existing production-router/middleware probes: peer receipt reads
  produce 404 and changing limiter instance obtains a separate allowance.
  These tests expose limits; their passing does not establish cluster safety.
- Focused pytest result: **118 passed, 6 skipped**. Skips are not proof.
- Deployment-claims, compose-secrets, merge-markers and suite-inventory gates
  each returned exit 0; logs `/tmp/860-382c5f39-check-*.log`.
- Architecture correction to the prior report: accepted ADR-082526-b36a DOES
  define heartbeat renewal and expiry reclamation through the canonical
  Attempt seam. The earlier fencing ADR's limited scope is not evidence that
  reclamation is absent. This corrects the architecture reconciliation in
  `issue-860-9ec969b5-repair.md`; it does not establish live RC reclaim behavior.
  Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and the mechanics-only
  runtime contract (ADR-081426-1f7c); no competing recovery/scheduler is needed.

## Executed validation

All commands ran in the assigned worktree, with 1000-second tool timeouts:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-deployment-claims.py
uv run python scripts/check-compose-secrets.py
uv run python scripts/check-merge-markers.py
uv run python scripts/check-suite-inventory.py
```

Every command passed. Vulture: 1322 reviewed identities / 1322 findings,
zero unclassified or prohibited findings, against the supplied base. Format:
3301 files. Inventory: 17 suites, 31323 unique identities; collection is not
execution of those suites. No source or tests changed, so no inventory-delta
note is necessary. No full package suite or live PostgreSQL soak was run.
The referenced schema regression now explicitly expects the three validation
audit columns (`test_pg_learnings.py:175-177`), independently of production
constants; it is not repaired by relaxing the fence assertion.

## Acceptance audit

All ten issue-level promotion criteria remain **UNVERIFIED**:

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC load profile | Read `m3a-load-profile.md`: one API key and degraded model calls, with explicit gaps for users/Workspaces, graph fan-out, successful tools/models, Design/Canvas and background work. No RC-specific applicability decision supplied. |
| Two deployed application replicas | Compose declares two replicas; executed probes use ASGI instances, not a deployed RC. |
| Sustained saturation, queues, reclaim, retries and leaks | Focused unit/contract tests passed; no sustained live run executed. |
| No duplicate physical work | Admission and fence tests do not establish physical execution uniqueness under deployed failover. |
| Replica-selection-resistant rate/security/degraded behavior | Executed `test_replica_selection_has_an_independent_production_allowance` (both auth cases): each instance independently returns `[200,200,429]`. `rate_limit.py:32` documents process-local state. This falsifies a shared-budget claim, not the documented local contract. |
| Complete telemetry and thresholds | Profile defines thresholds; no fresh exact-RC observations of application-loop latency, pool saturation, workers and reclaim. |
| Active-work restart/drain/fencing/recovery | Not executed live. Existing production-router probe (`tests/test_soak_promotion_gates.py:569`) reproduces peer receipt 404. That is visibility failure, not proof of lost physical work. |
| Long soak of exact RC artifact/configuration | `scripts/soak/run_soak.py:744` unconditionally rejects artifact equivalence. Executed promotion tests confirm fail-closed behavior; no immutable RC image/config supplied and no production-capable soak executed. |
| Findings classified to earliest broken invariant | This report distinguishes CI health, local admission/visibility limits and absent promotion evidence. Completeness of external finding classification is UNVERIFIED; no GitHub mutations permitted or performed. |
| Hash-bound machine/human soak evidence | This is a local validation report, not a production evidence pack. No new exact-RC machine-readable soak evidence exists from this round. |

## Disposition and next step

**BLOCKED** for issue acceptance. CI-repair inspection is complete: the supplied
failure is stale and the exact vulture gate is green. Do not add invented
ledger entries, weaken gates, or treat another short emulator run as promotion.
The only changed file is this report; inherited work is preserved.

The next acceptance attempt needs an explicitly selected immutable RC image,
normalized deployment configuration and supported workload scope, reachable
model gateway, and an exact-topology runner. Then execute the profile's >=4-hour
soak with physical Attempt observations and active-work interruption. Reconcile
the replica-budget claim and receipt visibility before asserting cluster-wide
security/recovery. Reuse the canonical heartbeat/reclaim seam, not a new
scheduler. No deployment or service state was changed in this round.

Checkpoint: checked 1 assigned issue; done 0 acceptance-complete issues;
skipped 0 assigned issues; reproduced CI errors 0; next: RC prerequisites and
production soak. Local commit required for this report; no push or PR action.

