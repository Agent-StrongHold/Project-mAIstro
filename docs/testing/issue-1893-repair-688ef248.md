# Issue #1893 repair — job 688ef248

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `2d00a313c04c3c2b8d84a32e77eaa6794e00a653`; supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: issue #1893; investigate supplied `test: failure` and exact-debt-ledger evidence. No other issue/PR will be processed or fetched.
- Frozen implementation review: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, adjacent codec/identity tests, their inventory notes, and relevant CI/ADR configuration. Review existing reachability changes without modifying ledgers/grants. Only the explicitly permitted vulture ledger may be amended if an executed scan warrants it.
- Initial tree clean. No salvage necessary.
- Ambiguity: dispatch supplies a job-level `test: failure`, not a failing test node. Proceed by reading local logs and executing focused validation; do not invent a failure.

## Progress

Read all five driver logs: sync/lint/format/inventory pass; focused tests report 201 passed, 3 skipped. Read supplied prior result and issue body; these are historical evidence, not fresh acceptance proof.

Fresh checks at the starting SHA:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings, zero unclassified. No vulture amendment warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL, both admission modules are new unreachable modules and new dispositions lacking trusted-base authorization (169 -> 171). All other sub-ratchets pass. Exact base resolved before execution.

The standing blocker is reproduced, not resolved. Reachability ledger/grant edits or fake runtime wiring are outside this lane's authorization. Continue only focused acceptance validation; no speculative source repair.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: 201 passed, 3 skipped; no supplied test failure reproduced.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16466 nodes, no duplicate evidence.
- Read accepted ADRs 081226-9944, 082526-7f02 and 083126-5e62. Preserve canonical ownership, immutable admission provenance and trusted-base authority. No activation or alternate authority is authorized by this repair.
- Local PostgreSQL 18.6 is available; database `maistro_1893_688ef248` verified absent before creation. The skipped tests do not count as durability proof.

## Live database validation

Executed at starting source SHA (only this report changed):

```sh
createdb maistro_1893_688ef248
DATABASE_URL=postgresql:///maistro_1893_688ef248 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_688ef248 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_688ef248 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy --junitxml=/tmp/1893-688ef248-live.xml
```

- Empty disposable database migrated through real chain 001->062; final revision confirmed by SQL.
- **204 passed, zero skipped**, including unbound/bound/acknowledged raw-versus-production pool cases.
- Production/raw PostgreSQL session PID pairs: 128142/128143, 128144/128145, 128146/128147. All sessions name `maistro_1893_688ef248` over local Unix sockets. Each case records exactly one persisted admission row.
- Fault injection: escaped lone surrogate stored in each snapshot TEXT column; both readers fail safely while preserving header fingerprint. No mocked DB or SQLite substitute.
- Final SQL counts: task_idempotency=0, canonical_runs=0, canonical_node_runs=0, canonical_attempts=0. Disposable DB retained.
- No new mutation/pre-fix test or destructive downgrade run in this round.

`uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped, 6 warnings**. This adjacent run had no PG DSNs; skips are not durability evidence. Warnings are aiosqlite worker threads reporting closed event loops in `test_sqlite_store.py`.

## Acceptance accounting

| Criterion | Evidence / limitation |
| --- | --- |
| Required interfaces; frozen/slotted header; named fields; strict UUID hex and signed timestamps | Inspected production codec and constructors; focused schema/scalar/UUID tests and mypy PASS |
| Fresh flat SQL mapping and v2 snapshot/binding/acknowledgement round-trip | Three-state unit and real PostgreSQL tests PASS; independent binding shape assertions at test_admission_codec.py:134-137 |
| Legacy bound/unbound/partial/receipt-only evidence without identity invention | Focused legacy tests PASS, including absent receipt, unreadable identities and whitespace |
| Header/full-decode separation and row/header mismatch rejection | Preservation/mismatch tests PASS; no clock or incoming fingerprint accepted |
| Typed fail-closed schema/format/header/snapshot/record errors and safe diagnostics | Focused duplicate/nonobject/nonfinite/precision/Unicode tests PASS, with suppressed exception chains and validated hash assertions |
| Evidence tags and arbitrary program_context preserved without fingerprint recalculation | Tagged-nonfinite and round-trip tests PASS; codec does not decode tags or recompute fingerprint |
| Same migrated schema, required DSNs, non-None pg_pool, raw/production TEXT compatibility | Live three-state tests PASS with distinct session identities and zero residue |
| model_of/model_of_json materialization; Run INSERT yields JSONB object | UNVERIFIED: inactive codec stores snapshot text, does not materialize models or insert Run payloads |
| Authorized Workspace/Project, explicit principals and registered Graph kinds in production admission | UNVERIFIED: tests construct identity strings; they do not exercise an authorized production admission |
| No new SQL mutation, HTTP/queue behavior, assessment/claim decision, scope/fingerprint utility or authority | Inspected codec source; no runtime consumer found by production import search. Only codec-to-identity and whitelist imports exist. B2 remains intentionally inactive |
| Focused tests, lint, formatting, scoped mypy and inventory | PASS; no tests added/removed, so no new inventory-delta note required |
| Unchanged full required CI and provenance | Full integration CI UNVERIFIED; required provenance FAILS at the exact supplied base |
| Supplied test failure repaired | UNRESOLVED: no failing node/traceback supplied and focused/adjacent runs pass |

## Disposition and handoff

**BLOCKED**, not merge-ready. The prior block is reproduced: both admission modules and their dispositions lack trusted-base authorization. This is not a develop-sync conflict. Vulture passes, so the exception for vulture ledger repair supplies no legitimate change. Do not add fake callers, activate C behavior, amend reachability ledgers/grants or weaken gates to conceal the failure.

Only `docs/testing/issue-1893-repair-688ef248.md` changed; no production/test/ledger/grant edits or GitHub mutations. The report is committed locally as the required checkpoint. This is a validation-only handoff, not a successful code repair or integration approval.

Progress: checked=1, done=0, skipped=0, errors=1. Next: owner-governed resolution of trusted-base reachability authorization/coordinated integration, plus the exact failing CI test log before another repair of this unchanged source is dispatched.
