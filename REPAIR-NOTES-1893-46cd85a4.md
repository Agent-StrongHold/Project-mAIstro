# Issue #1893 repair validation — 46cd85a4

## Frozen scope

Only issue #1893 in assigned worktree `/home/dev/Git/wt/auto-1893`, branch auto-1893. Exact starting HEAD `823b6e8ba6fc1ae643c4da1d7d913259efd4c47c`; supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064`. Initial worktree clean; no salvage necessary. Process admission_codec.py, admission_identity.py, their adjacent tests, existing admission inventory notes, relevant ADRs and CI gate evidence, and this report. Vulture ledger only if the exact scan supplies genuine findings. No remote enumeration/mutation, activation or reachability grant/ledger changes.

## Initial evidence and assumptions

Read frozen dispatch issue body and driver check-0 through check-4 logs. Sync, ruff, format and suite inventory passed; driver focused tests: 324 passed, 3 skipped. Skips are not PostgreSQL durability evidence. The reported `test: failure` has no failing node in supplied driver logs. Assumption: reproduce locally before changing code; no speculative repairs. Previous reachability authorization blocker must be checked against the pinned supplied base; a passing candidate scan alone cannot authorize it.

## Reproduced required-gate results

At starting HEAD, with 1800-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings / 1322 reviewed, zero unclassified. No Vulture ledger amendment is warranted.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are unauthorized new unreachable modules and dispositions (169 trusted -> 171 candidate). Other wrapper subgates pass. Logs: `/tmp/1893-46cd-vulture.log`, `/tmp/1893-46cd-provenance.log`.

This confirms the prior blocker independently. The Vulture-only exception cannot authorize reachability ledger changes; production activation remains outside B2. No merge conflict is present. Remaining validation will check representation behavior, not invent a policy repair.

## Focused validation

- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: 324 passed, 3 PostgreSQL skips (327 nodes).
- Production source import search finds only codec -> identity and a Vulture whitelist import; no runtime codec caller. Tests and exports do not establish runtime reachability.
- Read codec/identity implementation, complete codec tests, existing B2 inventory history and relevant accepted ADRs 081226-a66b, 082526-7f02, 083126-5e62. Reconciliation: immutable evidence creates neither execution nor authorization authority; trusted-base policy cannot be overridden by candidate bookkeeping. Goal -> Graph -> Run -> NodeRun -> Attempt is unchanged.

Docker has a running PG18 container; live durability validation will use a fresh dedicated database, never an existing/shared fixture database. The focused suite does not reproduce the reported hosted `test` failure.

## Live PostgreSQL validation

Created fresh disposable database `issue1893_46cd85a4` on the verified running `maistro-postgres` container, after checking the database did not already exist. Local credentials were resolved in-process and are not recorded. No existing database was reused/truncated.

- PostgreSQL **18.6**; `DATABASE_URL=<disposable DSN> uv run alembic upgrade head`: PASS, real empty-to-head migration chain 001 through **063**, including 055. Log: `/tmp/1893-46cd-migrate.log`.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` pointed to that database; `MAISTRO_REQUIRE_PG_LEGS=1` enforced non-skipping.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-46cd-pg.xml`: **204 passed, zero skipped**, 1.53s. Output: `/tmp/1893-46cd-pg.log`.
- Both pool sessions identified database `issue1893_46cd85a4`, server `172.20.0.2/32:5432`. Production/raw backend PID pairs: unbound **359000/359001**, bound **359002/359003**, acknowledged **359004/359005**.
- Each state persisted exactly one admission row, independently read through raw and production-codec pools. Bound and acknowledged inserts satisfied migration 055's paired identity constraint. Escaped-surrogate corruption was injected into each TEXT snapshot and rejected safely through both readers.
- Independent final SQL: `alembic_version=063`, `count(*) FROM task_idempotency=0`. Database retained locally as disposable evidence; no production data touched.

## Adjacent validation

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1919 passed, 310 skipped, 6 warnings**, 48.94s (2229 nodes). Log: `/tmp/1893-46cd-adjacent.log`. This separate run had no PostgreSQL DSNs; skips are not durability proof. Warnings are aiosqlite worker threads encountering closed event loops in the adjacent SQLite suite, not failed assertions.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16543 nodes, no duplicate identities/files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

## Acceptance audit

| Criterion | Executed evidence / boundary |
| --- | --- |
| Exact immutable DTO/header interfaces and fresh flat SQL mapping | Source inspection and focused round-trip, constructor and mapping isolation tests passed. Named column mapping retained. |
| Strict storage UUID hex, signed timestamps, supported formats and matching header | Focused UUID, scalar-range, bool/float-format, missing-column and header-mismatch tests passed. |
| Legacy bound/unbound/partial, no invented identity | Focused legacy tests passed, including receipt-only, one-sided, unreadable evidence and pair-without-receipt. A pair lacking receipt cannot satisfy the prerequisite DTO and remains explicit partial evidence. |
| Scalar evidence survives malformed full decode | Expiry/fingerprint preservation tests passed. Codec takes neither a clock nor incoming fingerprint; consumer replacement/409 precedence is not B2 behavior. |
| Strict TEXT JSON and safe errors | Duplicate/nonobject/nonfinite/deep-nesting/precision-loss/UTF-8 tests passed; live corruption injection passed. Safe messages and suppressed parsing chains asserted. |
| Snapshot tags and original fingerprint unchanged | Tagged nonfinite and canonical byte round-trip tests passed. Original-model fingerprinting and `model_of`/`model_of_json` materialization end to end remain UNVERIFIED: tests use handcrafted snapshots and a fixed fingerprint. |
| Raw/production pool compatibility on real schema | 204 no-skip passes after actual migration chain, independent sessions, one persisted row per case, zero final admission rows. |
| Run JSONB object (not doubly encoded), arbitrary context materialization | UNVERIFIED through a production caller; B2 has no Run INSERT or materializing consumer. |
| Real principals, authorized Workspace/Project and registered Graph kinds | UNVERIFIED through admission. Representation fixtures use synthetic identity strings; these are not authorization or transaction tests. |
| Canonical authority and stage limits | No SQL mutation, HTTP mapping, queue, live assessor, scope utility, scheduler, authorization or deletion policy changes by this repair. No activation claimed. |
| CI/reachability/quality | Ruff, format, scoped mypy, Vulture, inventory and shipped-surface passed; required provenance FAILED. Full integration CI and hosted `test` failure reproduction remain UNVERIFIED. |

No source or test change is supported by the measured evidence. No new tests, inventory delta or pre-fix/mutation failure is claimed. Existing inventory notes remain historical evidence, not authority. The `test` CI job includes other packages/frontends/root integration suites; this package-scoped validation cannot prove the entire job green.

## Handoff: BLOCKED

Only this report changed. Required provenance still rejects candidate reachability bookkeeping for both inactive admission modules. No Vulture finding exists to repair, and its explicit exception does not permit reachability grants or fake runtime wiring. Resolution needs trusted-base coordination/authorization under the two-merge rule or an explicitly authorized real consumer integration outside B2. Obtain the actual failing node/log at the assigned head before another test-repair dispatch.

No remote mutation, merge, push, grant edit or gate weakening performed. Local report commit is evidence handoff only, not integration approval or issue closure. Residual risks: inactive production contract, unproven materialization/authorization/full CI, and reproduced required provenance failure.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base coordination and actual failing-node evidence}`.
