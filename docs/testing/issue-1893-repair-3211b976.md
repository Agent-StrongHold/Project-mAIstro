# Issue #1893 repair checkpoint — 3211b976

## Frozen scope

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `74a218286abcc648178ea4a40522b4351ce7d212`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: issue #1893, existing immutable admission codec and adjacent identity tests. No other issues/PRs will be processed.
- Clean starting worktree. Inspect existing implementation, repository guidance/ADRs, captured dispatch evidence, driver check logs, and relevant CI commands. Edit only evidence-backed defects in the assigned codec/tests, necessary inventory notes, or this validation report. Vulture ledger amendment only if the explicitly requested scan demonstrates retained unbanked identities.
- Ambiguity: generic CI `test: failure` has no failing node in the dispatch prompt. Treat as an unverified report, not permission for speculative edits.
- Existing reachability ledger/disposition edits are inherited; no authorization to alter those ledgers or create grants. Recheck the exact provenance gate before determining disposition.

## Progress

Driver logs inspected: sync/lint/format/inventory pass, but focused pytest is only 201 passed / 3 skipped (not durability proof). Independently executed Vulture scan passes with 1323 reviewed identities / 1323 findings. Independently executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` fails (exit 1): two new unreachable modules and two unauthorized dispositions for admission_identity/admission_codec. Local origin/develop and the merge base both resolve to the supplied base. No sync conflict or changed base is present. Logs: `/tmp/1893-3211-vulture.log`, `/tmp/1893-3211-provenance.log`.

No GitHub mutation, fetch, merge, activation, or gate change performed. Vulture ledger needs no amendment; the exception does not authorize reachability ledger/grant changes. Root ruff check and format check, scoped mypy for both source modules, core suite inventory, and shipped-surface gate independently pass (`/tmp/1893-3211-{ruff,format,mypy,inventory,surface}.log`). Accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62 reviewed: preserve the canonical lifecycle, immutable admission provenance, and trusted-base authorization. Import inspection finds no runtime consumer (only codec -> identity and Vulture whitelist -> enum). A staged leaf cannot gain reachability through fake imports or self-authorization.

Read codec, identity constructors, focused tests and destructive pg_pool scratch setup. PostgreSQL 18.6 is available locally; verified `maistro_1893_3211b976` is absent before creating a new dedicated disposable database. Created this database and ran the real Alembic chain from empty through revision 062 (including 055). With both MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL pointing to it and MAISTRO_REQUIRE_PG_LEGS=1, the codec and identity tests pass: **204 passed, zero skipped**. Direct final SQL confirms revision 062 and 0 admission rows / 0 distinct generations / 0 distinct bound Runs. Logs `/tmp/1893-3211-migration.log`, `/tmp/1893-3211-focused.log`, `/tmp/1893-3211-focused.xml`, `/tmp/1893-3211-db-counts.log`. No other database was used. No downgrade test was run.

## Executed commands and evidence

All validation used the starting source SHA above and 1800-second command timeouts. Only this report changes; no source/tests/ledgers/grants/gates were edited, so no test inventory delta is required.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1; mandatory exact-debt-ledger step at `.github/workflows/vulture-ratchet.yml:77` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `createdb maistro_1893_3211b976` | PASS, new disposable DB |
| `DATABASE_URL=postgresql:///maistro_1893_3211b976 uv run alembic upgrade head` | PASS, real chain from empty through 062 |
| `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_3211b976 MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_3211b976 MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-3211-focused.xml` | PASS, 204 passed, zero skipped |
| `psql -d maistro_1893_3211b976 -Atc 'SELECT version_num FROM alembic_version; SELECT count(*),count(DISTINCT generation_id),count(DISTINCT run_id) FROM task_idempotency;'` | `062`, `0\|0\|0` |

Live tests require non-None pg_pool and compare named TEXT columns through raw and production `_register_json_codecs` connections. Each persists one scoped admission row, then injects escaped lone-surrogate TEXT into request, receipt and provenance snapshots, proving both readers preserve bytes while the full decoder fails typed and the header survives. Tests restore snapshots and delete their rows.

Session properties in the JUnit XML (all database `maistro_1893_3211b976`, Unix socket address/port NULL):

| State | Production PID | Raw PID | Scoped rows |
| --- | --- | --- | --- |
| unbound | 3780709 | 3780710 | 1 |
| bound | 3780711 | 3780713 | 1 |
| acknowledged | 3780714 | 3780715 | 1 |

An independently executed process-local mutation changed encoder output to `task_id=None`, then ran the existing bound round-trip test via `pytest.main`. It failed at `packages/maistro-core/tests/tasks/test_admission_codec.py:134` as expected; the harness asserted TESTS_FAILED and exited 0 (`/tmp/1893-3211-mutation.log`). This proves the SQL binding assertion detects the named historical regression independently of encode/decode agreement. No on-disk implementation changed.

## Acceptance audit

All test evidence below comes from this run, not earlier reports. It proves a staged codec, **not reachable production admission**.

| Criterion | Evidence / limitation |
| --- | --- |
| Exact interfaces, frozen/slotted header, six error codes | Source inspection of admission_codec.py and passing scalar/header/error/immutable DTO tests; no clock or incoming fingerprint input |
| V2 round-trip preserves snapshots and fresh flat SQL mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` passes in three states; `test_encode_returns_a_fresh_flat_mapping` passes; binding mutation fails as expected |
| Owner token storage-only hex, strict UUIDs, signed timestamps | Named owner token and generation validation tests plus invalid scalar/identity cases pass; messages omit raw owner tokens |
| Legacy bound/unbound/partial distinctions without invented identity | Named distinction, receipt-only, missing-receipt, unreadable and whitespace evidence tests pass; #1851 requires receipt identity, so a pair without receipt remains partial rather than inventing it |
| Expired legacy header invents no identity | Named test passes, preserving scalars without a clock/expiry decision |
| Header preserves expiry across malformed snapshots | Named test and live corrupt-TEXT cases pass |
| Header preserves fingerprint across partial binding | Named test passes; codec does not compare incoming payloads |
| Unknown formats fail closed and supplied header must match | Unknown-format and scalar-mismatch cases pass |
| Tagged nonfinite snapshots retain evidence and stored fingerprint | Named tagged test passes; tags remain objects, fingerprint is passed through rather than recomputed |
| Invalid/duplicate/nonobject/bare nonfinite JSON fails safely | Named rejection and nesting/numeric/Unicode/predecoded-value cases pass, including live TEXT injection |
| Raw/production pools see identical TEXT on migrated schema | Three live cases pass against migration 055 within the real chain; final zero row/identity counts verified |
| SQL field mapping, optional binding and acknowledgement | Three-state round-trip, immutable receipt identity and acknowledgement constraints pass; completed_at ignored |
| No SQL mutation, assessment, HTTP/queue/scope/policy change or competing execution authority | Pure Mapping-to-DTO implementation inspected; no production consumer found, and this round changes no implementation |
| Required integration CI and no self-authorized unreachable slice | NOT SATISFIED: trusted-base provenance gate fails; unchanged full integration CI UNVERIFIED |

**UNVERIFIED:** production `encode_evidence` and `model_of`/`model_of_json` materialization (the tests hand-build tags), arbitrary permitted program_context through that materialization path, fingerprinting original models before tagging, Run payload `$n::text::jsonb` object insertion, real authorized principals/Workspace/Project/registered Graph admission, and transaction/crash/dispatch invariants. Positive codec DB tests use DTO identity strings, not an authorized production admission. Consumer expiry/409 precedence belongs to C/F2 and is not established here. Coordination and activation policy remain external prerequisites.

## Blocker and handoff

The exact gate rejects inherited entries at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`: 169 trusted versus 171 candidate unreachable/dispositioned modules. Removing bookkeeping would conceal actual unreachable code; importing the codec only to satisfy reachability would be fake wiring. Neither is a valid repair. The Vulture-only ledger exception cannot authorize these reachability changes. Required next action is an externally authorized integration-base/consumer decision; no new grant or production activation may be invented by this worker.

Captured check metadata was inspected once for the reported generic `test: failure`. The supplied failing `test` check is for linked head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head, and its output title/summary/text are NULL. No attributable current-head traceback was supplied or reproduced. This ambiguity is **UNRESOLVED**; obtain the actual current-head CI failing node/log before a test repair. Do not continue speculative reruns or cosmetic edits.

Verdict: **BLOCKED**. Only this evidence report is committed locally; no push, GitHub mutation, merge, closure or integration approval. Disposable DB remains available. Progress: checked 1, done 0 implementation repairs, skipped 0, errors 1 mandatory gate; next: external authorization/base decision and attributable test traceback.
