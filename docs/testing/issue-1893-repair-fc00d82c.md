# Issue #1893 repair audit — fc00d82c

## Frozen scope

- Assigned item: #1893 only; branch `auto-1893`.
- Starting HEAD: `7f4a3f2dd208fb8aba06263e76f9d4b8aa2c7b6f`; assigned base: `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect existing admission codec, identity contracts, adjacent tests, relevant ADRs,
  CI workflows and their ledger gates. Only this audit file is planned for editing
  unless validation identifies a concrete in-scope code defect.
- No remote mutations, activation, invented production consumer, or reachability
  ledger/grant changes. The explicit Vulture exception applies only if its scan
  actually identifies retained unbanked identities.

## Initial evidence and assumptions

Read supplied `check-0.log` through `check-4.log`: dependency sync, Ruff and format
passed; focused tests reported 312 passed / 3 skipped; core inventory matched
16540 nodes. These are driver results, not independent validation.

The prior result reports unauthorized reachability rows and no reproducible test
failure. Assumption: the generic `test: failure` requires fresh reproduction,
not a speculative change. Production activation remains outside this leaf.

## Independently reproduced gate results

- Validated assigned base resolves before use.
- `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run python scripts/check-ratchet-provenance.py`: FAIL. Reachability and disposition subgates reject `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` as new, unauthorized entries. Other provenance subgates pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed findings, zero unclassified or never-allowlist. No Vulture amendment is justified.
- No merge conflict exists. The blocker is trusted-base reachability authorization, not a develop-sync conflict. This lane cannot authorize it by modifying candidate ledgers.

- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3292 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -rs`: **312 passed, 3 skipped**, 1.61s. All skips require both PostgreSQL DSNs; no durability proof from this run.
- Captured dispatch check records contain historical `test` failure for linked #1855 head `3f2c79a70d9e...`, without a failing-node log, and `exact-debt-ledger` failure for #1945 head `fcc8b437f209...`. Those are not the assigned HEAD. No speculative repair of those different heads.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082526-1899 and ADR-083126-5e62. Reconciliation: immutable admission evidence remains distinct from Attempt dispatch identity; tests/exports cannot replace real runtime use; candidate ledger entries cannot authorize new debt. No competing lifecycle or authorization path will be introduced.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16540 collected nodes, zero duplicate identities or byte-identical test files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: **15467 passed, 1070 skipped, 3 xfailed, 54 warnings**, 237.60s. The generic test failure did not reproduce in this package. Warnings include aiosqlite workers encountering closed event loops and an unawaited fake-process coroutine; these are not codec failures and are not repaired here.
- Production import search (`rg` across package Python excluding tests) finds only the codec importing identity and `_vulture_whitelist.py:105` importing `AdmissionAssessment`. No runtime caller of the codec exists; this agrees with `admission_codec.py:50-53` and the reachability gate. The initial more restrictive glob search returned no matches; the corrected search above is the evidence.

## Acceptance audit

All execution results above use the starting source SHA. Only this audit document
changed; no new tests, inventory delta, mutation run, runtime code, or ledger edits.
Existing historical inventory notes are not reinterpreted as fresh execution.

| Criterion | Evidence and limit |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, named columns | Source `admission_codec.py:127-299` defines required enum, error, header and three public functions. Focused tests exercise mapping and header contracts. No SQL positional row decoding. |
| Strict schema/version, storage UUID hex, signed timestamp validation and matching header | Focused tests pass for unknown formats, bool/float format rejection, missing columns, scalar mismatches, out-of-range timestamps, invalid UUID storage forms and v2 constructor failures. |
| Fresh flat v2 encoding, immutable snapshot and binding round trips | Three state tests at `test_admission_codec.py:127-152` pass; independently assert the paired `task_id=receipt_id`/Run storage shape. Fresh-mapping test passes. DTO tests pass. |
| Legacy bound/unbound/partial, no fabricated identity | Bound/unbound/one-sided, receipt-only, bound-without-receipt, whitespace/corrupt identity, ignored completed-at tests pass. Constructors require explicit receipt identity; insufficient evidence is partial rather than an invented receipt. |
| Minimal header independent of snapshot/binding validity | Expired-header, snapshot-failure expiry preservation and partial-binding fingerprint preservation tests pass. No clock or incoming request fingerprint is accepted; no claim, assessment, HTTP or queue mutation occurs. Consumer replacement/409 ordering is outside B2 and UNVERIFIED. |
| Strict TEXT JSON and safe typed errors | Duplicate/nonobject/bare nonfinite/overflow, excessive nesting, lossy numeric evidence, UTF-8 and predecoded-object rejection tests pass. Error tests check no raw data in messages and suppressed exception chains. |
| Tagged evidence and unchanged fingerprint | Pure tagged-nonfinite and Unicode/numeric preservation tests pass. They demonstrate codec pass-through of stored hashes, not production request fingerprinting. Full request/receipt/Run materialization using `model_of`/`model_of_json`, arbitrary permitted context and original-model fingerprinting is UNVERIFIED end to end. |
| Real migrated PostgreSQL raw/production codec contrast | UNVERIFIED this round: 3 tests skipped for absent DSNs. No database/migration/transaction/session or row-count proof is claimed. No disposable database was provisioned. Run JSONB object (not double encoding) acceptance is also UNVERIFIED. |
| Explicit authorized principals, Workspace/Project, registered Graph kinds | UNVERIFIED through production admission: codec tests use representation-only fixture strings, not authorized admission. No fake caller introduced to disguise this gap. |
| Required quality gates and production reachability | Ruff, format, scoped mypy, Vulture, package inventory, shipped-surface and core tests pass. Trusted-base reachability/dispositions FAIL; actual consumer absent. Full cross-package integration CI and additional promotion gates beyond the passing provenance subgate are UNVERIFIED. |
| Staging/scope constraints and canonical execution model | Preserved: report-only change, no new scheduler, Goal/event authority, authorization path, activation or legacy/deletion response policy. Coordination/activation choices remain unresolved; no merge approval implied. |

## Handoff

**BLOCKED** by inherited unauthorized reachability entries, not by unbanked
Vulture identities. `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614` fail the required provenance
step at `.github/workflows/vulture-ratchet.yml:77`. The Vulture exception does
not authorize reachability ledger/grant changes. Resolving this requires a
separately reviewed trusted-base authorization/coordination decision or an
explicitly authorized real consumer integration; neither is this B2 repair.
Do not retry this same unchanged assignment expecting a candidate-side ledger
amendment to fix trusted-base authorization.

Changed file: `docs/testing/issue-1893-repair-fc00d82c.md` only. No concrete codec
regression was reproduced, so no speculative repair was made. Remaining risks:
missing original failed-test details for this head, unexecuted live PostgreSQL
and end-to-end materialization, and required provenance failure.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base authorization/coordination}`.
This report is the local committed handoff, not integration or activation approval.
