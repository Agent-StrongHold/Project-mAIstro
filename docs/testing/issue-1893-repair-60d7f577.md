# Issue #1893 repair — job 60d7f577

## Frozen scope

- Issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `11b61227544a7be4d2024be73097016ae0a881b7`.
- Assigned develop snapshot: `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Initial working tree clean; no salvage required.
- Inspect admission codec, immutable identity types, adjacent tests, relevant ADRs,
  supplied driver logs and exact CI gate definitions. Only repair demonstrated
  failures within this issue; no runtime activation or reachability ledger edits.
- Ambiguity: dispatch reports `test: failure` without a failing node, alongside
  a previously reported provenance blocker. Reproduce focused checks before
  selecting any code change. Existing verification claims are not fresh evidence.
- No new issue/PR enumeration or remote mutations will be performed.

## Results

- Supplied driver logs: dependency sync, Ruff and formatting pass; focused tests
  report 312 passed / 3 skipped; inventory reports 16540 nodes. These are driver
  evidence, not live database proof.
- Fresh `uv sync --locked --extra dev`: PASS.
- Fresh `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed findings,
  zero unclassified/never-allowlist. No Vulture ledger amendment warranted.
- Fresh `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run
  python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both admission
  modules are new unreachable modules and new dispositions without trusted-base
  authorization. Other provenance subgates pass. The base resolved before use.
- This is not a merge conflict or a Vulture debt failure. The permitted Vulture
  exception cannot repair reachability provenance. No candidate grant, fake
  runtime consumer or ledger deletion will be used to bypass this blocker.

- Fresh `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: PASS,
  312 passed / 3 skipped (315 collected), 1.63s. All three database states skip
  at `test_admission_codec.py:470` because both required DSNs are absent.
- Fresh `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS,
  3292 files unchanged.
- Fresh `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, 2 files.
- Fresh `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Production import search (`rg -n 'admission_codec|admission_identity' packages
  -g '*.py' -g '!**/tests/**'`) finds only codec-to-identity import and the
  Vulture whitelist; no runtime codec consumer. The module explicitly records
  its staged status at `admission_codec.py:50-53`.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082526-1899 and
  ADR-083126-5e62. Reconciliation: preserve the canonical execution hierarchy,
  immutable admission provenance and Attempt-owned dispatch; test imports and
  candidate bookkeeping cannot establish runtime use or authorize new debt.

- Fresh `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: PASS (exit 0); full output preserved at
  `/tmp/1893-60d7f577-core-pytest.log`. The reported `test: failure` was not
  reproduced in the changed package. Service skips and thread warnings are
  not treated as production durability evidence.
- Fresh `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16540 collected nodes, zero duplicate
  identities or byte-identical files. No tests added, so no inventory delta.

Core summary: **15467 passed, 1070 skipped, 3 xfailed, 60 warnings in 243.55s**.
Warnings include aiosqlite worker threads encountering closed event loops.

## Acceptance audit at the starting source SHA

| Criterion | Fresh evidence / limit |
| --- | --- |
| Required interfaces, frozen/slotted header, immutable DTOs, fresh flat SQL mapping | Source inspection and passing focused header/round-trip/encode/identity tests. No positional column decoding. |
| Strict UUID hex, signed timestamps, matching header, constructor validation | Passing storage-UUID, scalar, mismatch and invalid-v2 tests. Bound encoding independently asserts task_id equals receipt_id and run_id is present. |
| Legacy bound/unbound/partial; no guessed work identity | Passing legacy tests distinguish both IDs plus explicit receipt from neither-set, partial pairs, receipt-only and pair-without-receipt. The latter fails partial rather than inventing the receipt required by #1851. completed_at supplies no authority. |
| Header/full decode separation and fail-closed unsupported format/schema | Passing expiry/fingerprint preservation, malformed snapshot, partial binding, missing-column and unknown-format tests. Consumer expiry/409 precedence is outside B2 and UNVERIFIED. |
| Strict TEXT object snapshots and safe typed errors | Passing duplicate/nonobject/bare-nonfinite, excessive nesting, lossy-number, surrogate, predecoded-value and suppressed-chain tests. No raw snapshot/token in error text. |
| Tagged context preservation, unchanged fingerprint | Tagged nan/inf/-inf round trips and arbitrary nested numeric/Unicode tests pass. They use constructed evidence tags; actual original-model fingerprinting plus encode_evidence/model_of/model_of_json materialization is UNVERIFIED. |
| Raw and production pools on real migrated disposable PostgreSQL | UNVERIFIED: all three pool-contrast tests skipped for missing DSNs. No DB session identities, final row counts, migration-chain or Run JSONB object-shape evidence claimed. |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED as production admission: fixture identity strings establish DTO representation, not authorization. |
| Focused pytest, lint, format, mypy, inventory and required integration gates | Listed focused checks and full core suite pass. Vulture/shipped-surface pass; provenance fails for reachability/dispositions. Full cross-package CI and remaining standalone gates UNVERIFIED. No new tests or inventory changes. No fresh mutation/pre-fix run claimed. |
| Reachable production behavior | No codec consumer found; test imports and exports are not runtime proof. Staged leaf status preserved, not misrepresented as integrated behavior. |
| No SQL mutation, HTTP/queue/assessment/clock/scope-policy change or competing authority | Source remains representation-only; this round changes only this report. No activation or coordination decision made. |

## Handoff — BLOCKED

Changed file: `docs/testing/issue-1893-repair-60d7f577.md` only. No production,
test, gate, grant or ledger edits: no repairable test failure or Vulture finding
was reproduced. Validation ran against the starting source SHA.

Required provenance at `.github/workflows/vulture-ratchet.yml:77` still rejects
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614`. Resolution requires separately
reviewed trusted-base authorization/coordination or an explicitly authorized
real consumer integration. This lane cannot manufacture either through its
Vulture-only exception. There was no develop-sync conflict to resolve.

Residual risks: original CI failing node/log unspecified; production consumer,
live database, end-to-end materialization and full integration acceptance remain
unverified. Repeating unchanged-head repair jobs cannot resolve this provenance
blocker. Owner intervention is required; this is not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base authorization/coordination}`.
No push, PR, merge or other GitHub mutation performed. Evidence committed locally.

