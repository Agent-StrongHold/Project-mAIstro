---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — job 2b100e

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`1824d19f7dd6f057961cf3118f0aadcce236cf82`, base
`a586560170a9ce4d72ee7d750100d0178c1f69d0`. Worktree initially clean.
Review the existing audit pagination implementation, its adjacent tests,
relevant ADRs, supplied check-0 through check-7 logs, prior result artifact,
and integration-scope/vulture gate definitions. Candidate edits restricted to
issue-358 audit implementation/tests, this note, and reviewed vulture identities
if the required scan actually reports debt. No remote mutations or scope expansion.

## Initial evidence / ambiguity

Supplied check-3 fails at `test_pm_workflow_api.py:271`: the live service reports
MaistroCoreBridge but returns a legacy unpaginated list to a non-admin. This
could be a deployment mismatch; do not weaken the test to accept that response.
Assumption: first establish local route behavior and live-service provenance.
Supplied check-6 uses an unregistered inventory suite
`packages/hive-conductor/tests`; use the registered e2e suite recipe instead.
Other supplied logs report passing lint, format, targeted tests and inventories;
these are driver evidence, not independently reverified yet.

## Named gate checkpoint

Executed the exact requested Vulture command with a 1,200-second timeout. It
fails trusted-base authorization: 1,342 reviewed identities versus 1,346
findings, four `get_page` declarations (protocol, SQLite, PostgreSQL, memory).
There is no candidate-ledger mismatch to amend. The reachable production caller
is `backend/services/audit_bridge.py:186`; deleting these APIs would break audit
pagination. A candidate ledger change cannot authorize them; no artificial
references or duplicate ledger entries will be introduced.

Read the prior result and ADR-037/073. Retain canonical admin-only decision
audit and indefinite event retention (purging belongs to #325). No execution or
authorization authority changes. The integration-scope workflow aggregates six
specialized CI producers, not a standalone implementation test. Actual remote
producer conclusions are absent from the supplied job: remote failure cause
UNRESOLVED. Further local validation cannot manufacture those conclusions.

## Independent acceptance checkpoint

- Focused Conductor audit/convergence/noop tests: **76 passed** (20.13s).
  Legacy SQLite million-row migration: 10.033s; first page 0.0007s; scoped page
  0.0004s; maximum query VM instructions <2,800.
- Core `test_audit_pages.py`: **8 passed, 4 skipped** (10.63s). Canonical SQLite
  million-row load: 9.062s; maximum query VM work 3,400. PostgreSQL cases skipped
  because no `MAISTRO_TEST_PG_DSN` is configured; runtime remains UNVERIFIED.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,878 files).
- Read-only httpx probe of the test's resolved live `/openapi.json`: HTTP 200;
  audit GET has only action/severity/actor parameters and an **array** response.
  This is not this checkout's cursor/page contract. Deployed revision unknown;
  no changes to shared running services or their data.

Source review confirms database scope/filter predicates before LIMIT, native
streaming export, and frontend 500-entry retention with viewport slicing.
Browser execution remains UNVERIFIED. The reachable legacy memory path still
copies/sorts the full corpus (`audit_query.py:402`); core ephemeral memory also
scans all entries. Thus the unconditional corpus-independent initial-cost
criterion is NOT MET even though indexed durable queries meet the measured
bound. Do not relabel this limitation as completed acceptance.

## Integration/inventory checkpoint

The frozen manifest's scope classifier succeeds and selects PostgreSQL, Hive
API/UI, wheel imports, and Docker build. Executing
`uv run python scripts/check-integration-scope.py --event-name merge_group
--scope-json <classifier output>` fails: all six producer conclusions are
missing locally. No remote failure cause can be inferred from absent evidence.
Do not pass fabricated `--result ...=success` flags.

Confirmed all four retained APIs already appear in
`quality/vulture-baseline.json:1004,1013,1075,1174`; no bookkeeping amendment
is justified. Trusted-base approval is external to this repair.

Initial inventory checks rejected this note's inline empty inventory block;
corrected it to explicit zero deltas using the required multiline syntax.
The driver's check-6 suite path is invalid; the registered recipe is
`packages/hive-conductor/tests/e2e` (`check-suite-inventory.py:155`).

## Final results and handoff

After correcting the note, all three registered inventory commands pass:

- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`: 3,369.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`: 23.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: 12,714.
- `git diff --check`: passed.

Executed test commands (1,200-second timeout):

```text
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s
```

| Acceptance criterion | Evidence / gap |
| --- | --- |
| Bounded cursor, stable ordering, maximum page | Focused route and adapter tests pass; live deployment does not match candidate. |
| Database scope before pagination | SQLite query and authorization tests pass; PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Source reviewed; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus load | Server tests pass; native NDJSON download source reviewed, browser behavior UNVERIFIED. ADR-037 indefinite event retention preserved. |
| Representative query/index measurement | Both SQLite million-row envelopes executed; PostgreSQL UNVERIFIED. |
| Concurrent inserts, stable cursors, scope isolation, max limits, empty pages, million-row envelope | 76 backend + 8 core tests pass; 4 PostgreSQL cases skipped. |
| Initial page cost independent of corpus | Durable SQLite proven; NOT MET by reachable memory scan/sort paths. |
| Bounded browser memory/DOM | 500-entry cap and viewport slicing in source; runtime UNVERIFIED. |

Only this note changed; no tests added, no ledger/gate/grant edits, no code
repair claimed. Verdict **BLOCKED**. Next requires trusted-base authorization
for the four retained APIs, actual failed integration producer logs, and a
candidate-matching isolated deployment for API/browser validation. The memory
fallback performance gap remains separate from those CI blockers. Do not keep
retrying this identical evidence-only lane as though it could approve grants
or update the external deployment.

Progress: checked 1 issue; done 0 implementation repairs; skipped 0 issues;
errors 2 unresolved named gates. Commit this handoff locally; no GitHub actions.
