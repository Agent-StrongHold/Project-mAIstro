# Issue #1893 repair — 407df2a4

## Frozen scope

- Assigned head: `5cb7c545095464a297df8039825181d9d3a7e138` (verified; clean worktree).
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 B2 codec CI repair. Supplied dispatch-context.json is the frozen issue/PR evidence; no GitHub refresh or mutations.
- Inspection: admission codec, admission identity DTOs, adjacent tests, relevant ADRs, CI workflow/gate scripts, supplied check logs.
- Candidate edits: evidence in this file; codec/tests only if a reproduced defect requires repair; vulture ledger only if the named scan identifies reviewed debt. No reachability ledger/grant changes.
- Ambiguity: the dispatch says `test: failure` but gives no failing node. Treat as unproven attribution until supplied logs or local validation identify it.
- Existing work was clean; no salvage required. This round does not authorize production activation or new consumer wiring.

## Results

- Driver logs `check-0.log` through `check-4.log` inspected: dependency sync, Ruff, format, focused tests (201 passed / 3 PG skipped), inventory (16466 nodes) succeeded. These do not establish PostgreSQL acceptance.
- Both frozen base and local `origin/develop` resolve to `3c761d14db944a727fa0744444bc67cfe36d49f7`; no develop-sync conflict exists.
- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0, 1323 findings, zero unclassified. No evidence warrants a vulture ledger amendment.
- Executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` have unauthorized new unreachable-module and disposition entries. Other subgates passed. This independently reproduces the previous blocker; this lane cannot self-authorize it.
- Independently executed root `uv run ruff check .`, `uv run ruff format --check .`, scoped `uv run mypy` on codec/identity, focused `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`, `uv run python scripts/check-shipped-surface-truth.py`, and `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: all exit 0. Tests: 201 passed, 3 skipped; inventory: 16466 nodes, zero duplicate evidence.
- Read codec, identity constructors and adjacent codec tests. Confirmed tagged test fixtures are manually constructed, not production model materialization or authorization evidence.
- Captured failed `test` check in the frozen dispatch names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this assigned head; output title/summary/text are null. Current-head failing node/traceback remains UNRESOLVED. No speculative source repair is justified.
- Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Preserve the canonical execution hierarchy and immutable admission provenance; candidate evidence cannot grant itself authority. Runtime import search found only codec -> identity and Vulture whitelist -> identity, not a production codec consumer. No activation or fake wiring is permitted to bypass the failed gate.
- Verified PostgreSQL 18.6 and absence of `maistro_1893_407df2a4`, then created that dedicated disposable DB. Executed `DATABASE_URL=postgresql:///maistro_1893_407df2a4 uv run alembic upgrade head`: actual empty-to-062 chain passed, including migration 055. No downgrade tests run.
- Executed `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_407df2a4 MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_407df2a4 MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-407df2a4-live.xml`: 204 passed, zero skipped. Required non-None production-codec pool and independent raw pool exercised the same migrated schema in three binding states. Each case asserts one persisted scoped row and injects corrupt escaped-surrogate TEXT at all three snapshot boundaries, preserving the header while rejecting full decoding.
- `psql -d maistro_1893_407df2a4 -Atc 'SELECT version_num FROM alembic_version; SELECT count(*), count(DISTINCT generation_id), count(DISTINCT run_id) FROM task_idempotency;'`: `062`, `0|0|0`. Disposable DB retained; no existing database modified. Source under test remained the assigned SHA; commands used 1800-second timeouts.
- JUnit recorded production/raw backend PIDs: unbound 3893385/3893386, bound 3893387/3893389, acknowledged 3893390/3893392. All sessions identify `maistro_1893_407df2a4` over Unix sockets (address/port NULL).
- Executed a process-local mutation via `uv run python`: wrapped `encode_admission_record` to replace encoded `task_id` with None, then invoked the existing bound round-trip node using `pytest.main`. Expected failure occurred at `test_admission_codec.py:134` (`None != 'rcpt-1'`); harness asserted TESTS_FAILED and exited 0. No source/test file mutated. This proves the migration-055 binding regression cannot pass merely because encoder and decoder agree.

## Acceptance audit

| Criterion | This round's evidence |
| --- | --- |
| Frozen/slotted header; exact decode/encode interfaces and six typed errors | Source inspection and 204 passing codec/identity tests; scoped mypy passes |
| V2 snapshots preserved, flat fresh mappings, owner hex only at storage | Three-state byte round-trip, owner token/strict UUID tests, fresh mapping and live SQL tests pass |
| Strict signed scalar fields and matching header | Invalid scalar, format, missing column and header-mismatch tests pass |
| Legacy bound/unbound/partial; no invented receipt or work identity | Named legacy tests, receipt-only and missing receipt cases pass. Bound task/run pair lacking receipt remains partial because #1851 binding constructor requires actual receipt evidence |
| Header expiry/fingerprint survives malformed snapshot/partial binding | Both named header-separation tests pass; expiry decisions and mismatch classification remain outside the codec |
| Unknown formats never become legacy | Named unknown-format test passes for seven unsupported values and mismatched supplied headers |
| Tagged nonfinite snapshots without fingerprint change | Named nan/inf/-inf tests pass, with manually tagged fixtures; codec does not recalculate fingerprints or decode tags |
| Invalid/duplicate/nonobject/bare nonfinite JSON and unsafe exception chains | Named malformed JSON, nesting, numeric-loss and Unicode cases pass; safe typed error assertions pass |
| Raw and production JSON codec TEXT independence on migrated PG | Three live pool cases pass, distinct sessions/same DB, one row per case and final zero residue; no SQLite/fake/skip evidence used |
| Named SQL fields, both binding columns, acknowledgement and ignored legacy completion | Live three-state round-trip and independent binding mutation prove SQL shape; completion-is-never-read test passes |
| No SQL/HTTP/queue/_assess/scope/clock/claim/policy production changes | Pure mapping codec inspected; only this report changes in this round; canonical Goal -> Graph -> Run -> NodeRun -> Attempt retained |
| Production evidence-json/model materialization and arbitrary program_context | UNVERIFIED: fixtures manually construct tags, not actual `encode_evidence`/`model_of`/`model_of_json` request/receipt/Run materialization |
| Original-model fingerprint before tagging; Run JSONB payload object, not double encoding | UNVERIFIED: codec preserves a stored fingerprint but these tests do not establish production fingerprint creation or Run INSERT behavior |
| Real explicit principals, authorized Workspace/Project, registered Graph | UNVERIFIED: DTO test identity strings are not authorization/admission proof |
| Lint/format/types/inventory | Commands above pass; no new tests or inventory delta, so no inventory note changes required |
| Unchanged required integration CI / authorized reachability | NOT SATISFIED: exact-debt-ledger provenance fails. Full integration CI UNVERIFIED; supplied failed test names another head |

## Blocker and handoff

`quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` add two modules beyond the trusted base. The mandatory command at `.github/workflows/vulture-ratchet.yml:77` rejects them. Candidate ledger editing, fake imports or enabling an out-of-scope consumer cannot repair that authority failure. Vulture has no unbanked identities, so the lane's vulture-only exception does not apply. Required next step is an externally authorized base/consumer decision (any approved grant must already be on the trusted base), plus an attributable current-head test traceback before source repair.

Verdict: **BLOCKED**. No implementation, test, ledger, grant, gate or GitHub changes. Only `docs/testing/issue-1893-repair-407df2a4.md` is committed locally. No push, merge, issue closure or activation approval.

Progress: checked 1, done 0 implementation repairs, skipped 0, errors 1 mandatory gate; next: external authorization/base decision and current-head CI evidence.

