---
inventory-delta:
  packages/hive-conductor/backend/tests: 4
---

# Issue 358 repair — ca6daf

## Frozen scope

Only issue #358, starting HEAD eef5a1e60db6d64f660d681b4f354d8ee04415db,
and the already in-progress merge of assigned develop base
f5fa43771103d140c7d485959e914aa8fce33079. No remote enumeration or mutation.
Scope: audit route conflict; audit query/UI and adjacent tests for validation;
explicit vulture ledger repair; evidenced format and inventory-note gate failures.
Incoming staged and unstaged work preserved outside the worktree in
`../incoming-358-ca6daf-index.patch` and `../incoming-358-ca6daf.patch`.

## Initial evidence

Driver check-1/4: conflict markers in backend/routes/audit.py block imports.
check-2: two incoming files fail formatting.
check-3: external HTTP endpoint returns legacy array instead of page envelope;
assumption: validate against this worktree's application, not an unidentified service.
check-5/6: incoming p0-1-principal-migration-wave2a inventory front matter invalid.
Merge HEAD already equals supplied develop base; finish that merge in place.

## Results

Vulture initial command reports two identities already banked by the incoming
base (`Principal.audit_label`, `Principal.has_permission`), but compares against
pre-merge b4b9e187e29b. Recheck with the supplied base as RATCHET_BASE_REV after
resolving merge; do not duplicate ledger rows.

Architecture conflict discovered: incoming P0.4 serves Container.audit_log,
while #358 pages the older JsonStore. A merge that simply retains #358's read
would regress the canonical audit authority (test_audit_convergence explicitly
requires core-only events to be visible). Canonical core reads must be preserved;
core cursor-query support is not established by the existing JsonStore tests.
Incoming P0.1 also removes state.user: audit scope now uses require_principal.

## Partial reconciliation (not acceptance)

Resolved the merge by retaining incoming canonical core reads and writes, and
#358's bounded legacy fallback. Core still returns its prior list contract;
this is NOT compatible with the paginated frontend and needs core-store cursor
support before integration. Export/detail/retention still target the legacy
store. Do not approve this partial repair for integration.

Read ADR-068, ADR-073, ADR-081226-6e34, ADR-081226-a66b and cutover P0.1/P0.4.
Core Sentinel decision reads are admin-scoped per accepted ADR-073, not exposed
as personal legacy events. No execution/scheduler/Goal authority is changed.
The Principal helper replaces the removed state.user authority. Export now
checks it before starting the streaming response; three parameterized tests
reject a spoofed legacy state.user on list/export/retention. One canonical
store test verifies a regular user cannot read Sentinel decisions.

Incoming inventory metadata corrected to a zero delta (no tests were added
by that Principal migration note); its file-change description remains below
the front matter. Incoming formatting failures were normalized only in the
two files named by check-2. Initial vulture findings cannot be compared against
the incoming base until the merge is committed (the gate uses merge-base).

## Executed validation, first pass

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2766 files).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_audit_convergence.py -x -q -s`:
  **53 passed**, including the four new regression cases and canonical-core
  visibility. Legacy million-row index build 9.086s, first page 0.0007s,
  scoped page 0.0004s, maximum measured query work <2800 VM instructions.
  This measures the legacy SQLite store, NOT the canonical core audit query.
- Inventory first rerun rejected inline `{}` as unsupported metadata; changed
  it to a documented zero suite delta. Final retries passed (below).
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  FAIL, all nine specialized producer results missing. This local aggregate
  cannot prove a CI repair without producer evidence; do not fabricate success
  arguments. Actual prior CI producer failure remains UNRESOLVED.
- `git diff --check`: PASS; the resolved audit file still awaits staging.

- Regression proof: runtime-only restoration of the old dict scope made the
  new canonical-principal list test fail (200 != 401). No worktree code was
  reverted for this experiment.
- Production acceptance probe: added a runtime-only HTTP assertion to the real
  SQLite Container convergence test; **FAILED** because `/v1/audit` returns a
  list instead of `{entries, next_cursor}`. This reproduces the driver's
  legacy-envelope failure against THIS worktree, not an external endpoint.
- Inventory retry exposed a second malformed incoming note:
  `feat-cutover-p0.2-route-registry.md` counted `quality/: +3` despite stating
  "No Python test delta". Corrected to `tests/: 0` (no quality ledger edit).

## Final checkpoint / handoff

Merge committed locally as `58d060bb1`; no remote actions. The incoming
quality ledger/grant changes are exactly the supplied base's, not new grants:
`git diff f5fa43771103d140c7d485959e914aa8fce33079 HEAD -- quality/` is empty.
The two retained Principal identities are banked by that merge; no duplicate
ledger amendments were necessary.

Final gates:

- `RATCHET_BASE_REV=f5fa43771103d140c7d485959e914aa8fce33079 uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: PASS, 1359 reviewed / 1359 actual identities.
- Same base, `uv run python scripts/check-principal-identity.py`: PASS,
  4 tolerated / 4 actual violations, none new.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: PASS, 3270 collected.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/tests/e2e`: PASS, 23 collected.
  The driver's `packages/hive-conductor/tests` is not a registered recipe;
  used the explicit e2e recipe from the gate, without changing the gate.
- Ruff lint and whole-tree format checks passed again after code edits.

Files repaired beyond the supplied merge: `backend/routes/audit.py`,
`backend/tests/test_audit_routes.py`, `backend/tests/test_audit_convergence.py`,
format-only `backend/services/agent_materialization.py` and core
`graph/durable_runs/canonical_store.py`, this note and the two malformed
incoming inventory notes named above. All other merged files preserve the
already staged assigned-base integration.

Acceptance assessment:

1. Bounded cursor / stable order / maximum limit: legacy path tested; FAIL on
   reachable canonical core path (executed page-envelope probe).
2. Database authorization before pagination: legacy SQL scope tests pass;
   canonical pagination unavailable. Core decision audit restricted to admin
   under ADR-073, not broadened to regular users.
3. Incremental virtualized frontend: inspected but browser execution UNVERIFIED
   this round; canonical list response breaks the expected envelope.
4. Filters/export/retention without browser corpus: legacy scoped, capped
   export tests pass; canonical export/detail and retention remain unresolved.
   Actual purge absent; #325 remains coordination owner, not proof of completion.
5. Representative large dataset: legacy million-row SQLite measurements above;
   canonical core query/index envelope UNVERIFIED.
6. Concurrent inserts, stable cursors, isolation, limits, empty pages and million
   rows: executed legacy audit suite passes; no corresponding canonical core
   page API exists to validate those invariants.
7. Initial cost independent of corpus: legacy durable SQL measured; memory path
   still sorts the corpus (`audit_query.py`); canonical path unproven.
8. Browser memory/DOM bounded: code inspection only this round, UNVERIFIED.

Residual integration risk is real, not scanner noise: the core/legacy read
contract and corpus split must be resolved through the existing canonical audit
store, with DB-scoped cursor APIs and measured production-backend tests. Do not
replace core audit with the old JsonStore or fabricate a cursor over its first
10,000 core rows. Integration-scope also needs actual specialized CI producer
results; nine missing results are not evidence of a particular code failure.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 2
(canonical pagination, missing integration evidence). Partial repair committed.
Next: implement/validate pagination on canonical audit authority, then validate
frontend against it and obtain specialized integration evidence. No new items.

Logs are in job ca6daf9c9cf74d20b152f8a2d8f79c30, `repair-*.log`.
