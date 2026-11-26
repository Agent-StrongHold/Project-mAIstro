# Issue #1893 repair — a9d10e2c

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `916d0765f951e83578d4cbba09c615ac01d61ab9`; supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: issue #1893. Review its `admission_codec.py`, `admission_identity.py`, their two test files, related ADRs, inventory notes and named CI gates. No other issues or PRs will be processed.
- Initial worktree clean. No salvage required. No GitHub mutations or activation authorized.
- Ambiguity: dispatch reports only `test: failure`, without failing test output. Treat it as unlocalized; reproduce focused tests and inspect supplied evidence rather than guess a code repair.
- Existing reachability ledger modifications are outside the permitted vulture-ledger repair exception. Do not change grants, dispositions, baselines or gates to bypass authorization.

## Initial evidence

Read the issue body from the supplied immutable dispatch snapshot. Driver logs: dependency sync passed; Ruff check passed; format check passed (3277 files); focused tests 201 passed, 3 skipped; core inventory 16466 nodes matched. These are driver observations, not this worker's execution or live database proof.

## Independently reproduced gate result

Executed the exact requested Vulture command: PASS, 1323 reviewed identities / 1323 findings (`/tmp/1893-a9d1-vulture.log`). No unbanked identity exists to repair or amend.

Executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), two unauthorized new unreachable modules and two unauthorized dispositions, for `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` (`/tmp/1893-a9d1-provenance.log`). Local `origin/develop` and merge base both resolve to the supplied base; no sync conflict is present. No ref was fetched or changed.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62: preserve canonical execution hierarchy, immutable admission provenance, and trusted-base gate authority. The vulture-only exception does not authorize a reachability grant. This failure cannot be repaired by candidate bookkeeping, fake production imports or unauthorized activation. Further validation is scoped to distinguishing codec correctness from integration readiness; the mandatory gate remains blocked.

## Focused validation checkpoint

Independent commands passed: root Ruff check and format check; scoped mypy for codec and identity; focused pytest; shipped-surface truth; core suite inventory. Logs `/tmp/1893-a9d1-{ruff,format,mypy,focused,surface,inventory}.log`. Source and adjacent tests reviewed. Runtime source import search finds only codec -> identity and Vulture whitelist -> identity; no runtime codec consumer. Test imports and whitelist references are not production admission reachability.

PostgreSQL 18.6 is available. Verified the new disposable database name `maistro_1893_a9d10e2c` does not exist. Reviewed pg_pool fixture: it truncates scratch tables and registers production JSON codecs. Created only this dedicated database, migrated the real chain and ran the three raw/production pool contrast cases with required PG legs, never against an existing database.

## Executed commands and outcomes

All commands used the starting source SHA and 1800-second validation timeouts. No implementation, test, ledger, grant or gate changed; only this report changes. No test inventory delta is needed.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed / 1323 found |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1, two unreachable modules and two dispositions unauthorized |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` | 201 passed, 3 skipped; not durability proof |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 collected nodes, zero duplicate evidence |
| `createdb maistro_1893_a9d10e2c` | PASS, previously absent dedicated disposable DB |
| `DATABASE_URL=postgresql:///maistro_1893_a9d10e2c uv run alembic upgrade head` | PASS, actual empty-to-062 migration chain, including 055 |
| `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_a9d10e2c MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_a9d10e2c MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-a9d1-live.xml` | **204 passed, zero skipped** |
| `psql -d maistro_1893_a9d10e2c -Atc 'SELECT version_num FROM alembic_version; SELECT count(*), count(DISTINCT generation_id), count(DISTINCT run_id) FROM task_idempotency;'` | `062`, `0\|0\|0` |

Live migration, test and count logs: `/tmp/1893-a9d1-{migration,live,counts}.log`. All PG sessions target `maistro_1893_a9d10e2c` via Unix socket (address/port NULL). Production/raw backend PIDs: unbound 3840503/3840504; bound 3840505/3840506; acknowledged 3840507/3840508. Each case asserts exactly one scoped persisted row; final SQL confirms zero admission rows/generations/bound Runs. Tests require a non-None production-codec pool, use an independent raw pool and named TEXT columns, inject escaped lone-surrogate TEXT into each snapshot, assert typed rejection with preserved header, then restore/delete test rows. No downgrade or transaction/crash test was run.

A process-local mutation replaced encoded `task_id` with None before invoking the existing bound round-trip node via `pytest.main`; the node failed as expected and the harness asserted TESTS_FAILED (harness exit 0, `/tmp/1893-a9d1-mutation.log`). No file was mutated. This checks that the historical migration-055 binding regression is detected independently of encode/decode agreement.

## Acceptance audit

Evidence below is independently executed in this round; passing DTO tests is not production admission reachability.

| Criterion | Evidence / limits |
| --- | --- |
| Exact header/record/encoder interfaces; frozen/slotted header; six decode codes; #1851 types | Inspected source, passing immutable DTO, scalar, schema and typed error tests |
| V2 byte-preserving snapshots and fresh flat mapping | Three-state `test_v2_round_trip_preserves_all_snapshot_bytes` and `test_encode_returns_a_fresh_flat_mapping`; binding mutation detected |
| Owner storage-only hex, strict UUIDs, signed timestamps and safe diagnostics | Owner token, generation hex, invalid scalar/identity, repr hygiene and typed failure tests pass |
| Legacy bound/unbound/partial distinction without guessed identity | Named distinction, receipt-only, missing receipt, unreadable and whitespace evidence tests pass. Constructor needs receipt identity: bound pair without receipt remains partial, never fabricated |
| Expired header invents no identity | `test_expired_legacy_header_does_not_invent_missing_identity` passes; no clock/assessment added |
| Preserve expiry despite malformed snapshot; fingerprint despite partial binding | Both named header-separation tests pass; corrupt live TEXT also preserves header |
| Unknown formats fail closed; supplied header must match | Unknown format, schema and header scalar mismatch cases pass |
| Tagged nonfinite evidence and unchanged fingerprint | Named tagged round-trip test passes for nan/inf/-inf; codec leaves tags intact and passes through stored fingerprint |
| Invalid, duplicate, nonobject and bare nonfinite JSON rejected safely | Named rejection, nesting, lossy-number, Unicode and predecoded-value cases pass |
| Raw/production pool TEXT independence on real migration chain | Three live states pass with same database identity and distinct sessions; final zero rows verified |
| SQL field mapping, binding and acknowledgement | Three-state SQL round-trip passes; matching receipt and both binding columns enforced; legacy completed_at ignored |
| Typed representation only; no SQL mutation, HTTP/queue/_assess/scope/claim/clock/policy changes | Pure Mapping-to-DTO implementation inspected; no production consumer; no implementation changes this round |
| Focused tests, lint, format, applicable mypy and truthful inventory | Commands above pass; no new tests or inventory delta |
| Unchanged integration CI and no self-authorized unreachable slice | NOT SATISFIED: mandatory provenance gate fails; full integration CI UNVERIFIED |

**UNVERIFIED:** production `encode_evidence` and `model_of`/`model_of_json` materialization (fixtures construct tags directly), arbitrary permitted program_context through that production path, fingerprinting original model before tagging, Run payload `$n::text::jsonb` object insertion, real authorized principals/Workspace/Project/registered Graph admission, transaction/crash/dispatch invariants. DB tests use DTO identity strings rather than authorized admission. Consumer expiry/409 ordering belongs to C/F2, not this codec. Coordination and activation policy remain external prerequisites.

## Blocker and handoff

Mandatory CI step `.github/workflows/vulture-ratchet.yml:77` rejects inherited `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. The trusted base has 169 versus 171 candidate modules. Candidate bookkeeping cannot supply its own grant (accepted ADR-083126-5e62 and repository two-merge rule). Vulture passes, so the permitted vulture exception gives no applicable repair. Do not conceal unreachable code by deleting bookkeeping, or fake wiring via imports. Required next action: an externally authorized base/consumer decision; any approved grant must already be on the trusted base before revalidation. This worker may not create that grant or activate admission.

Captured check metadata independently inspected once: the supplied failed `test` check names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head; output title/summary/text are NULL. Current-head failing node/traceback is **UNRESOLVED**. No attributable test failure was reproduced. Obtain current-head CI evidence before attempting a code repair; no speculative or cosmetic source change is justified.

Verdict: **BLOCKED**. Only this report is committed locally. No push, merge, GitHub mutation or closure. Disposable database retained for inspection. Progress: checked 1, done 0 implementation repairs, skipped 0, errors 1 mandatory gate; next: external authorization/base decision and attributable test traceback.
