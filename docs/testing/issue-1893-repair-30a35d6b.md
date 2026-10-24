# Issue #1893 repair checkpoint — 30a35d6b

## Frozen scope

- Assigned item: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `41b73efdb0b3ba325e11820400821f99ff4bd857` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean starting worktree. No incoming edits to salvage.
- Inspect only admission_codec.py, admission_identity.py, their two test files,
  adjacent admission persistence/evidence/schema, relevant ADRs/workflow gates,
  and supplied dispatch/prior evidence. No GitHub mutations or activation.
- Potential edit scope: evidence-backed codec/test repair, associated inventory
  note if tests change, explicitly permitted vulture ledger only if the exact
  scan demonstrates retained unbanked identities, and this report.
- Ambiguity: dispatch names only `test: failure`, without failing node/output.
  Proceed by reproducing focused tests and named gates, not guessing a repair.

## Initial evidence

Read repository AGENTS.md and issue body from the frozen dispatch-context.json.
Driver check logs: dependency sync succeeded; ruff check/format passed;
identity + codec tests reported 201 passed, 3 skipped; core inventory reported
16466 nodes with no duplicate evidence. These are driver observations, not live
PostgreSQL acceptance proof and not a reproduction of the unspecified CI failure.

## Reproduced results

- Exact assigned Vulture scan: PASS, 1323 findings, zero unclassified. No
  evidence supports any vulture ledger amendment.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run
  python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both admission
  modules have new unreachable-module and disposition rows without trusted-base
  authorization. Base commit resolved before execution. This is not a sync conflict.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped (PostgreSQL), 204 nodes. Generic CI test failure not
  reproduced. Read prior result/report; their claims are not current proof.
- `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance gate.
  Vulture repair permission does not authorize changing reachability ledgers or
  grants. No speculative production change will be made to bypass this blocker.

## Architecture and further checks

Read both complete source modules and their tests, plus accepted ADR-081226-9944,
ADR-082526-7f02 and ADR-083126-5e62. Preserve canonical execution ownership and
immutable admission provenance; trusted-base policy cannot be self-authorized.
The issue's staged codec scope does not authorize inventing a runtime consumer
merely to satisfy reachability. Source import search confirms only the codec and
Vulture whitelist import these types; no production codec caller is present.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- Scoped `uv run mypy` on both source modules: PASS.
- Parsed captured check-run sources for failed conclusions: no matching failure
  output found. Generic `test: failure` remains unspecified, not repaired.
- Local PostgreSQL: 18.6. Checked `pg_database` before creating the dedicated
  disposable database `maistro_1893_30a35d6b`: no existing database of that name.

## Live validation

Executed against starting source SHA (only this report changed):

```sh
createdb maistro_1893_30a35d6b
DATABASE_URL=postgresql:///maistro_1893_30a35d6b uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_30a35d6b \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_30a35d6b \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy --junitxml=/tmp/1893-30a35d6b-live.xml
```

- Empty dedicated DB migrated through the real chain 001->062; SQL confirms
  `alembic_version = 062`. No fake pool or SQLite schema recreation.
- **204 passed, zero skipped**. All three raw/production pool cases executed.
- Production/raw PID pairs: unbound 4144551/4144552, bound 4144553/4144554,
  acknowledged 4144555/4144556. Both pools use the named DB over local Unix
  sockets; each case recorded exactly one persisted admission row.
- Injection: escaped-surrogate TEXT in request, receipt and provenance columns;
  both pools return a typed safe failure while preserving header fingerprint.
- Final SQL counts: admissions=0, canonical_runs=0, canonical_node_runs=0,
  canonical_attempts=0. Disposable database retained for inspection.
- No destructive downgrade or new pre-fix/mutation comparison performed.

Additional executed commands:

- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped**,
  five aiosqlite closed-event-loop worker-thread warnings. No PG environment
  supplied for this adjacent run; skips do not prove durability.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

## Acceptance accounting

| Criterion | Current evidence / limitation |
| --- | --- |
| Frozen/slotted header, exact interfaces, named scalar columns, signed timestamps and strict UUID hex | Source inspection, scoped mypy, focused scalar/owner/generation rejection tests PASS |
| Immutable v2 DTOs; bound/unbound/partial legacy evidence; no guessed identity | Focused identity, receipt-only, missing-receipt and partial-pair tests PASS |
| Header/full-decode separation; expiry/fingerprint preserved; mismatched header rejected | Focused preservation and mismatch tests PASS; codec takes no clock or incoming fingerprint |
| Unknown formats, malformed/duplicate/nonobject/bare-nonfinite JSON fail closed; safe errors | Focused format, snapshot, precision, nesting, Unicode and suppressed-chain tests PASS |
| Fresh flat mapping, owner storage encoding, three snapshots, optional binding/acknowledgement | Focused tests plus all three live migrated PG state round-trips PASS; test_admission_codec.py:134-137 asserts binding independently of encode/decode agreement |
| Tagged program_context survives without recomputing fingerprint | Tagged-nonfinite round-trip tests PASS; stored fingerprint and tags preserved |
| TEXT independent of raw/production JSON codec registration; same real schema and nonempty DSNs | 204 tests PASS, distinct sessions in same database and zero final residue as above |
| Model materialization through model_of/model_of_json; Run JSONB payload is object | UNVERIFIED: this inactive codec does not materialize task/Run models or insert Run payloads |
| Explicit principals, authorized Workspace/Project and registered Graph kinds | UNVERIFIED for production admission: tests exercise codec DTOs with identity strings, not authorization/Graph admission |
| No SQL mutation, live assessment, queue, HTTP, scope/fingerprint utility or policy changes | Source inspected; this round changes only this report |
| Focused pytest, ruff, format, applicable mypy, truthful inventory | PASS; no test additions/removals, hence no inventory delta required |
| Full unchanged integration CI and trusted-base reachability | UNVERIFIED full CI; required provenance gate FAILS |
| Reported CI test failure repaired | UNRESOLVED: no failing node/traceback supplied; focused and adjacent runs pass |

## Final disposition

**BLOCKED.** `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` add unreachable modules and
CONNECT dispositions absent from trusted-base authorization. The exact required
provenance gate independently reproduced this failure. An already-landed,
owner-governed authorization or coordinated runtime integration is needed;
this lane cannot create either merely to make an inactive slice green.
The passing Vulture scan provides no justification for a ledger amendment.

No production code, tests, baseline, grant or gate changed. No GitHub mutations,
merge, activation or issue-closure action taken. This report is the sole changed
file. Commit it locally after `git diff --check`; this is a blocked handoff,
not implementation repair or integration approval.

Progress: checked=1, done=0, skipped=0, errors=1. Next: resolve trusted-base
reachability ownership outside this lane and supply the exact failing CI test
traceback before dispatching another repair of the same unchanged source.

