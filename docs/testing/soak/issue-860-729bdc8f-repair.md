# Issue #860 repair — 729bdc8f

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`8941982581056b62fc55bfc6e32f4dfc92819899`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Worktree initially clean; no salvage required. No remote mutations.
Process the assigned exact-debt-ledger gate first, then focused soak acceptance
validation. Candidate edits limited to reviewed vulture identities/dead code
(if the actual scan identifies any), corresponding tests/inventory if needed,
and this report. Preserve all inherited work.

The supplied job directory has no `check-*.log` files. The prior result reports
BLOCKED; those claims are not accepted as new verification. No develop conflict
is present, so no speculative fetch/merge is planned.

## Results

The exact prescribed vulture scan passed: 1322 findings / 1322 reviewed
identities, zero unclassified and zero never-allowlist findings, using the
supplied base. No ledger repair is warranted. The cited historical `check-3.log`
failed a schema-fence assertion (24 statements versus 21 expected); targeted
current-head reproduction passed (see commands below). The prior report is retained as context,
not proof. This round is a writer repair; no production deployment or immutable
RC configuration has been supplied.

Focused pytest returned **118 passed, 6 skipped** in 2.17 seconds. Full-tree
ruff lint and formatting passed (3301 files). The historical schema assertion
failure did not reproduce. Existing executed production-middleware probes
confirm independent per-instance allowances; the production-router receipt
probe confirms a peer 404. Neither ASGI test establishes a deployed soak.

Read accepted ADR-081426-1f7c and ADR-082526-b36a: preserve canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt`, mechanics-only Runtime, and
Attempt heartbeat/lease reclamation. No replacement scheduler or recovery
system is justified. Read the load profile and artifact gate: the current
host-uvicorn driver explicitly cannot establish exact Compose RC equivalence.
No speculative gate or ledger changes will be made.

## Commands executed

All validation commands below returned exit 0 with 1200-second tool timeouts:

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

Inventory matched 17 suites / 31323 unique identities; collection is not suite
execution. No tests were added or modified, so no inventory delta is needed.
No full package suite or live soak was run. The inherited schema test now
independently expects the three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`;
no assertion relaxation was needed in this round.

## Acceptance audit

The frozen issue body's ten criteria were checked against the inspected runner,
profile, production middleware/router and executed tests. All remain
**UNVERIFIED at production promotion scope**:

| Criterion | Evidence / gap |
|---|---|
| Representative supported RC profile | `m3a-load-profile.md` explicitly leaves multi-user/Workspace, Graph fan-out, successful model/tool calls, Design/Canvas and background workload applicability unresolved. No selected RC scope supplied. |
| At least two deployed application replicas | Tests exercise two ASGI instances; not two deployed RC replicas. No live deployment was run. |
| Sustained saturation, queue growth, reclaim, retry and leaks | The 2.17-second unit/contract run cannot establish these observations. |
| No duplicate physical work | Admission assertions do not observe physical Attempt execution during failover. No new production uniqueness evidence. |
| Replica-selection-resistant security/rate/degraded behavior | Executed `test_replica_selection_has_an_independent_production_allowance` for both auth cases: each instance accepts two requests then returns 429. `rate_limit.py:32-37` explicitly documents local state and N-times aggregate limits. This disproves a shared allowance, not the documented local contract; acceptance reconciliation is still required. |
| Complete telemetry with explicit thresholds | Profile has thresholds, but no fresh exact-RC application-loop, pool, worker/reclaim or long-window telemetry was collected. |
| Active-work kill/restart, drain, fencing and recovery | Not executed live. Executed receipt probe at `tests/test_soak_promotion_gates.py:569` exposes peer 404 through the production router (`tasks.py:144-146`). Visibility failure alone does not prove physical loss/duplication. |
| Long exact-RC artifact/config soak | `scripts/soak/run_soak.py:744` always rejects artifact equivalence. Its host-process topology cannot satisfy this criterion even at four hours. No immutable RC image/configuration selected. |
| Findings classified to earliest broken milestone invariant | This report distinguishes stale CI evidence, process-local admission/visibility limits and missing release evidence. External classification completeness remains unverified; no issue mutations performed. |
| Hash-bound machine-readable and human-readable soak evidence | This report records local validation, not new production evidence. No new exact-RC machine-readable soak was generated. |

## Disposition

**BLOCKED**, not merge-ready. Only this report changed. The explicitly assigned
CI-repair gate needs no amendment; making one would be cosmetic or speculative.
All inherited work is preserved. No runtime, ledger, grant, deployment state or
authorization path changed.

Next prerequisite: identify the immutable RC images and normalized production
configuration, supported workload scope and reachable model gateway; provide a
production-topology runner with physical Attempt observations. Resolve the
rate-budget acceptance mismatch and receipt visibility before claiming cluster
safety, then execute the >=4-hour soak including active-work interruption.
Do not rerun this unchanged CI-only repair as if it could supply that evidence.

Checkpoint: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
reproduced CI errors 0; next: RC prerequisites and production soak.

