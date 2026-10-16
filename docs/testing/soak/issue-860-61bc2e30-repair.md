# Issue #860 repair — job 61bc2e30

## Frozen scope

Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `1f29b70935ee9dbb82d77a937363a53e885d76fb`,
base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
No PR processing or GitHub mutations. Initial worktree clean.

Repair candidates are the supplied schema-fence test failure in
`packages/maistro-core/tests/persistence/test_pg_learnings.py` and reviewed
identities reported by the required vulture gate in
`quality/vulture-baseline.json`. Related production schema and soak code/tests
are read/validation scope only unless the reproduced failure requires a fix.
This report and a test-inventory note (if needed) complete the write scope.

## Initial evidence and assumptions

Current job directory has no `check-*.log` files. Supplied prior log
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements
versus 21 expected. Reproduce against this HEAD before changing anything.
Prior result `923fa48010ba4732b29e7869df7347f3/result.json` reports BLOCKED,
not promotion evidence. Exact-RC artifact/configuration is not supplied by the
lane brief; local tests cannot substitute for its sustained production soak.

## Fresh validation checkpoint

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped (PostgreSQL-dependent coverage is not live evidence).
  The reported 24-versus-21 failure does not reproduce: the current test already
  independently lists all three Gauntlet audit columns at lines 173–175.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed; 1322 reviewed identities match 1322 findings; zero unclassified and
  never-allowlist findings. No ledger amendment is justified.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3301 files).
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.

The existing load profile expressly identifies representative-traffic and
exact-artifact gaps. Its host-process driver cannot certify the promoted Compose
artifact, even at four hours. Both supplied CI repair leads are already resolved
at the assigned HEAD; no speculative implementation edit is warranted.

- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  1 passed; canonical admission backpressure maps to retryable HTTP 429.
- `uv run python scripts/check-suite-inventory.py`: passed; 17 suites,
  31323 unique test identities. No test additions or changes; no inventory delta.

Commands used 600–1200 second validation timeouts. Two exploratory path lookups
were not found and skipped: `docs/testing/soak/README.md` and
`packages/maistro-server/src/maistro_server/routers/tasks.py`. The actual
profile and production `api/tasks.py` were subsequently read. These were lookup
errors, not failed validation commands.

## Architecture and acceptance assessment

Read repository instructions, the documentation authority hierarchy, the frozen
issue body, accepted ADR-081226-a66b (lifecycle) and ADR-081626-f383 (fencing),
and proposed ADR-081 (deployment). ADR-081 is not an accepted waiver. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; admission uniqueness does not
prove physical-work uniqueness. The accepted fencing contract explicitly does
not authorize implicit lease-expiry takeover. No competing execution, event,
store, scheduler or authorization path was introduced.

| #860 acceptance criterion | Fresh evidence and disposition |
|---|---|
| Representative RC load profile | UNVERIFIED: inspected `m3a-load-profile.md`; it explicitly lacks multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal-worker workloads. |
| At least two deployed application replicas | UNVERIFIED: two-instance ASGI probes executed, not two deployed exact-RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks | UNVERIFIED: no long production soak executed; unit probes cannot establish these observations. |
| No duplicate physical work, including Goal reconciliation | UNVERIFIED: admission evidence is not Attempt physical-work or sustained reconciliation evidence. |
| Replica-resistant rate/security/degraded behavior | NOT PROVEN: executed `test_replica_selection_has_an_independent_production_allowance` observes `[200, 200, 429]` independently on both instances for the same identity; canonical backpressure test passes. |
| Production telemetry with thresholds | UNVERIFIED: no fresh production pool/query/lock/application-loop/worker/RSS/descriptor/queue/error time series. Driver-loop samples are not application-loop evidence. |
| Active-work restart, graceful drain, fencing, recovery | UNVERIFIED: no deployed production restart performed. |
| Long soak of exact RC, repeated after changes | UNVERIFIED: no immutable promotion artifact/config supplied; `run_soak.py:744` explicitly rejects its host-process preflight as exact-RC evidence. Executed gate tests preserve that rejection. |
| Findings filed/reclassified at earliest broken invariant | UNVERIFIED: no fresh live soak or evidence of complete finding disposition; no GitHub mutation permitted. |
| Machine/human evidence bound to image/package/commit/config | UNVERIFIED: this report binds local checks to the starting commit, not to a promoted deployment. |

Reachable production seams corroborate the tests: `api/rate_limit.py:95`
constructs a limiter per middleware instance, and `api/tasks.py:144` reads its
injected task queue. The executed receipt probe at
`tests/test_soak_promotion_gates.py:564` uses the production router and one
shared canonical admitter, observing local 200 and peer 404. The rate probe at
line 439 uses production middleware, not a simulated limiter. These probes
establish the local limitations; they are not live load evidence. Existing
process-local budgeting is documented by its owner, so this lane does not
silently redefine it as a cluster-wide budget or add a new authorization path.

## Handoff

**BLOCKED**, not promotion approval. Only this report changed. Both reported
CI-repair leads are clean at the assigned head. No code/runtime configuration,
test, quality ledger, grant or existing evidence was changed. No synthetic
repair was made merely to produce a diff. The prior BLOCKED condition is missing
production acceptance evidence, not an unresolved merge conflict; no fetch or
merge was justified.

Next: identify the immutable RC image/configuration, resolve workload coverage
and replica-budget/receipt semantics with their canonical owners, then execute
and publish the long production soak including active physical work and recovery.
A short emulator run or another green unit suite cannot unblock promotion.

Progress: checked 1 issue; done 0 acceptance items; skipped 0 issues;
validation errors 0. All ten acceptance criteria remain unproven at promotion
grade. Local validation/handoff completed; residual risks are listed above.

