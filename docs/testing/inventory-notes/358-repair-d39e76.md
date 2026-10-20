---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — d39e76

## Frozen scope and initial state

Only #358 in `auto-358`, clean starting HEAD
`8b7eaf6870cdd67617b18a39866169d2d3ea7d22`, supplied develop base
`97c05e0f17e3ed72c82d76ed7eb0a0fe702883fb`.
Process the supplied manifest's audit pagination source/tests/migration/UI,
`quality/vulture-baseline.json`, the named integration-scope and Vulture gates,
and this note. Adjacent architecture/ADRs and CI contracts are read-only context.
No other issue, worktree, remote mutation, or grant change is in scope.

Driver check-3 fails at `test_pm_workflow_api.py:271`: the live endpoint returns
200 with an old array contract despite canonical health and `limit=1`.
The prior result reports a trusted-base Vulture authorization failure and
missing integration producer evidence; neither is assumed true until rerun.
Ambiguity: no specific integration producer log is supplied. Proceed by checking
the gate contract and report missing evidence rather than inventing success.

An initial instruction-file discovery accidentally listed sibling worktree
paths; none were read or changed. Further discovery is confined to this tree.

## First checkpoint

All eight supplied driver logs inspected. Checks 0/1/2 pass dependency sync,
lint and format; check 4 passes 76 tests; checks 5/7 pass inventories.
Check 6 fails because `packages/hive-conductor/tests` has no collection recipe.

Executed the exact requested Vulture gate (1,200-second timeout): **exit 1**.
Trusted base `c0441cf94b9a` has 1,343 reviewed identities; candidate has 1,347.
Four `get_page` identities (PostgreSQL, SQLite, protocol, in-memory audit) lack
trusted-base authorization. The gate explicitly says candidate `--update`
cannot authorize them. Review candidate banking and real callers before any edit.

Read ADR-073 and ADR-037: canonical decisions are admin-only; audit events are
persisted indefinitely by default. Do not weaken authorization or introduce an
unapproved purge policy to satisfy the issue. Read production audit routes:
list/export enforce canonical admin scope before querying; legacy reads use
actor scope. Retention reports policy metadata, not a purge implementation.

## Executed acceptance checkpoint

- Backend audit convergence/pagination/routes/noop contracts: **76 passed**,
  24.66s. Million-row legacy SQLite index migration 10.408s; first/scoped pages
  0.0010s/0.0006s; maximum query VM instructions <2,800.
- Canonical adapter audit pages: **8 passed, 4 skipped**, 12.72s. Million-row
  SQLite load 10.367s; maximum query VM work 3,400. PostgreSQL runtime remains
  UNVERIFIED because `MAISTRO_TEST_PG_DSN` is not configured.
- Classifier run with the exact frozen manifest surfaces: requires Docker,
  Hive API/UI E2E, PostgreSQL 17/18, wheels. Named integration gate: **exit 1**,
  all six producer conclusions missing. This reproduces missing local evidence,
  not the unspecified remote producer failure; remote cause remains UNRESOLVED.
- Candidate ledger already banks all four retained identities at lines
  1005/1014/1076/1175. Production caller is `audit_bridge.py:186` (outside the
  core-only scanner paths). No genuinely dead identity found; duplicating rows,
  fake callers, or changing scanner scope would not be a valid repair.
- `audit_query.py:402-403` snapshots and sorts the entire legacy memory corpus
  per request. Corpus-independent first-page cost is NOT MET for that fallback;
  durable indexed queries are the tested bounded path.

Commands so far (all validation timeouts 1,200s):

```
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run python scripts/ci_merge_group_scope.py --json <frozen manifest surfaces>
uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s
```

No production/ledger changes are justified by the named gate failures. A
trusted-base grant is a separate governance change, not authorized by this lane;
producer conclusions must be supplied for the actual integration candidate.

## Final validation and acceptance

Additional commands executed with 1,200-second timeout:

- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 2,852 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`:
  **PASS**, 3,352 identities.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  **PASS**, 12,591 identities.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
- `git diff --check`: **PASS**.

| Acceptance | Executed evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page | Backend and adapter tests pass: max 200, tie-breaking IDs, cursor continuation. External driver target still violates contract; target revision unknown. |
| Authorization/scope before database pagination | Production route denial-before-query and SQLite scope/filter tests pass; PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | `AuditLog.tsx` reviewed: cursor requests, sliced viewport. Browser runtime UNVERIFIED in this round. |
| Filters/export/retention without full browser corpus | Production filter and capped streaming export tests pass; retention constants endpoint passes. ADR-037 indefinite audit retention retained; purge is #325, not implemented here. Browser download runtime UNVERIFIED. |
| Large dataset query/index measurements | Both million-row SQLite tests executed, measurements above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum, empty pages | Executed backend/adapter tests cover all; four PostgreSQL cases skipped. |
| Corpus-independent initial cost | Proven for indexed SQLite queries; NOT MET for legacy in-memory fallback. |
| Bounded browser memory/DOM | Source retains at most 500 entries and mounts viewport slice; browser runtime UNVERIFIED. |

The passing backend suite includes
`test_pm_audit_contract_against_each_production_authority[legacy/canonical]`.
These execute the external PM assertion against local production routes/auth
and real stores for both bindings. Thus the driver's live-service failure is
not reproduced against these worktree routes. Do not accept an old array or
weaken the canonical 403 assertion to hide a stale/misidentified deployment.

## Handoff — BLOCKED

Changed file: this validation/inventory note only; no test-count changes.
No production, ledger, grant, gate, execution authority, or authorization edits.
No GitHub mutations, background commands, destructive Git operations, or work
removed. There is no develop-sync conflict in the clean starting worktree.

Required next inputs: separately landed trusted-base authorization for the four
retained APIs; failed specialized producer logs/conclusions for the actual
candidate; revision identification of the external E2E target. Candidate ledger
banking is already complete. Repeating a candidate ledger rewrite or note-only
repair cannot supply these inputs. Residual implementation/verification risks
are the memory-path cost and unexecuted PostgreSQL/browser acceptance above.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 2 named-gate
failures. Local validation complete; acceptance/integration approval withheld.
