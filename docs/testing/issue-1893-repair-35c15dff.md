# Issue #1893 repair — job 35c15dff

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `79eeacdd03a4cf0ebda39cc56aa86b0197d182bc` (verified).
- Assigned develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting working tree clean; no incoming work to salvage.
- Process existing admission codec/identity implementation and adjacent tests,
  supplied check logs, CI gate configuration, relevant ADRs, and this report.
  No additional issue or PR enumeration, GitHub mutation, or activation.
- Assumption: generic `test: failure` is not a reproducible defect until local
  evidence identifies it. Previously reported reachability authorization must
  be checked independently; vulture-only permission does not authorize other
  ledger changes.

## Driver evidence (not worker execution)

Supplied check-0 through check-4 logs: dependency check passed; Ruff check and
format passed; focused tests 201 passed / 3 skipped; core inventory matched
16466 nodes. PostgreSQL skips are not durability evidence.

## Worker results

- Independently executed exact Vulture command from the assignment: PASS,
  1323 reviewed findings, zero unclassified. No ledger amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run
  python scripts/check-ratchet-provenance.py`: FAIL. Both admission modules
  have new unreachable-module and disposition rows without trusted-base
  authorization. Local `origin/develop` resolves to this exact base.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped (PG legs), 204 collected.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS,
  3277 files formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

No implementation defect or Vulture debt reproduced. The independently
reproduced blocker is a reachability policy prerequisite, not a merge conflict;
no fetch or merge is warranted by this evidence.

- Read accepted ADR-081226-9944, ADR-082526-7f02, ADR-083126-5e62:
  canonical execution identities and immutable admission provenance remain
  unchanged; candidate quality bookkeeping cannot authorize itself.
- Source import search finds no production codec caller (only DTO imports
  from the codec and an enum import in the Vulture whitelist). Tests/exports
  are not reachability evidence; activating a caller is outside B2 scope.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 nodes, no duplicate evidence.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped,
  5 aiosqlite worker-thread closed-event-loop warnings. No PG environment in
  this broader run; skips do not count as DB acceptance.
- Confirmed local PostgreSQL access and that disposable database
  `maistro_1893_35c15dff` does not exist before creating it.
- Created that dedicated disposable DB; `DATABASE_URL=postgresql:///maistro_1893_35c15dff
  uv run alembic upgrade head`: PASS, empty DB through real chain 001->062,
  PostgreSQL 18.6.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both set to
  `postgresql:///maistro_1893_35c15dff`, and `MAISTRO_REQUIRE_PG_LEGS=1`,
  repeated the two focused files with `-x -q -o junit_family=legacy
  --junitxml=/tmp/1893-35c15dff-live.xml`: **204 passed, zero skipped**.
  Production/raw session PID pairs: 4021457/4021458 (unbound),
  4021459/4021460 (bound), 4021461/4021463 (acknowledged), all on the same
  local Unix-socket DB. Each case recorded exactly one persisted admission
  row and exercised surrogate-corruption rejection through both pools.
- Initial final-count query failed because `runs` is not the table name.
  Corrected query against `task_idempotency`, `canonical_runs`,
  `canonical_node_runs`, `canonical_attempts`: all four counts zero.
  DB retained for inspection; no downgrade/destructive migration test run.

## Acceptance accounting

All code executions above used starting HEAD; this round changes only this
report. No tests added/removed, so no inventory-delta note is required.

| Criterion | Executed evidence / limit |
| --- | --- |
| Exact frozen/slotted interfaces; named SQL columns; strict UUID hex and signed scalars | Scoped mypy and 204 focused tests pass, including header/scalar/generation rejection cases |
| Immutable DTO or typed failure without invented identity | Bound/unbound/partial, receipt-only, missing-receipt and unknown-format tests pass |
| Valid header survives malformed snapshot or binding; rejects scalar mismatch | Header expiry/fingerprint preservation and mismatch tests pass |
| Fresh flat encoding and exact three-snapshot round-trips | Three-state in-memory and live PG round-trips pass; storage binding columns independently asserted at test_admission_codec.py:134-137 |
| Strict object JSON, duplicate/nonfinite rejection, safe errors | Invalid JSON, numeric precision, nesting, Unicode, scope and owner-token tests pass |
| Tagged program-context evidence and unchanged fingerprint | Tagged-nonfinite round-trip passes; codec never materializes tags or recalculates fingerprint |
| Raw/production JSON-codec pools over real migrated TEXT schema | Three PG states pass on the same DB, nonempty DSNs, non-None production pool, distinct recorded sessions, zero residue |
| Model materialization via model_of/model_of_json; Run JSONB object INSERT | UNVERIFIED: no materializing consumer or Run INSERT in this staged codec |
| Explicit authorized principals, Workspace/Project and registered Graph | UNVERIFIED for production admission: codec tests use DTO identity strings, not authorization calls |
| No clock, classifier, mutation, HTTP mapping, queue or activation change | Source inspection: pure row codec; no production caller found; report-only repair |
| Inventory, Ruff, scoped mypy, Vulture and shipped-surface checks | Independently PASS as recorded above |
| Full unchanged integration CI and trusted provenance | NOT PROVEN: provenance gate fails; full integration CI not run |
| Reported test failure repaired | UNRESOLVED: focused and adjacent tests pass; no assigned-head failing traceback provided |

## Disposition

**BLOCKED**, not integration approval. Scope reconciled with accepted ADRs:
Goal -> Graph -> Run -> NodeRun -> Attempt remains the execution authority;
no dummy caller, competing authority, policy bypass or activation introduced.
The failed trusted-base gate requires an owner-governed prerequisite, not an
unauthorized reachability ledger edit. Vulture has no unbanked identities.
No speculative implementation or cosmetic scanner repair is justified.

Changed file: `docs/testing/issue-1893-repair-35c15dff.md` only. No GitHub
mutation, gate/grant/ledger edit, or issue closure. Next: owner supplies a
trusted-base reachability resolution and the exact current-head failing test
traceback if `test: failure` remains actionable. Progress: checked=1, done=0,
skipped=0, errors=1 (unresolved provenance blocker). Commit this report locally.
