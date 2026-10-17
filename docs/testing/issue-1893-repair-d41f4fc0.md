# Issue #1893 repair — d41f4fc0

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `1a80de163072a05cda982ee5a8ca036d5dbbb785`; supplied base `ac69535ef165ded3ca82cd3428728569de3251fa`.
- One item: reproduce the supplied `test: failure` and exact-debt-ledger evidence for #1893. No remote mutations or unrelated repairs.
- Initial worktree clean; no salvage necessary.
- Read-only review scope: supplied dispatch snapshot/check logs, repository instructions/ADRs, admission codec/identity types and adjacent tests, applicable CI gates and prior repair evidence.
- Write scope: this report; production/test repair only if an actual in-scope failure is reproduced. No reachability baseline/disposition/grant edits. The vulture ledger exception applies only to reviewed vulture identities if its specified check fails.

## Assumptions / progress

The assignment is a writer repair, not the verifier-only role. The generic `test: failure` has no failing node in the prompt; use supplied logs and focused validation rather than inventing a defect. Production activation is explicitly outside this leaf. Prior claims are not fresh acceptance evidence.

Initial snapshot inspected. Driver check-0 sync, check-1 Ruff, check-2 format, check-3 tests (311 passed, 3 skipped) and check-4 inventory (16467 nodes) all passed; no failing test traceback supplied.

Fresh execution: named Vulture command passed (1323 reviewed identities / 1323 findings), so no ledger amendment is justified. `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run python scripts/check-ratchet-provenance.py` exited 1: admission_identity and admission_codec each introduce an unauthorized unreachable module and disposition. The resolved trusted merge base is `3c761d14db94`; local origin/develop equals the supplied base. This is an authority blocker, not a merge conflict. No baseline/grant/gate changes or fake callers will be introduced.

## Focused validation at starting source SHA

All commands used a 1800-second timeout. This round changes only this report.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities |
| `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run python scripts/check-ratchet-provenance.py` | FAIL, four unauthorized reachability/disposition additions |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes: 311 passed, 3 skipped, 1.57s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16467 nodes, no duplicates |
| `git diff --check` | PASS |

No tests were added or changed; no inventory delta is needed. The reported generic CI `test: failure` is not reproduced by the supplied driver logs or focused execution. Full integration CI is UNVERIFIED; no test repair is claimed.

## Acceptance audit and architectural reconciliation

Read repository instructions, quality-gates policy, accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle) and ADR-083126-5e62 (candidate evidence cannot authorize itself). No competing execution, Goal, event or authorization authority was introduced. Read the supplied prior result as historical evidence only.

- Exact interfaces, frozen/slotted header, validated hashes/signed scalar timestamps, named columns, strict UUID hex, fresh flat parameter mapping: implementation inspection plus passing focused contracts. No SQL mutation in codec.
- Immutable v2 snapshots and owner token storage: passing three-state round-trip and token tests. Independent task/run/acknowledgement assertions at `test_admission_codec.py:134-137` pin the migration-055 shape; `admission_identity.py:291-292` enforces binding receipt equality. Actual database CHECK execution is UNVERIFIED this round.
- Legacy bound/unbound/partial and receipt-only evidence: passing tests, including missing receipt identity, invalid original data and whitespace. Reconciliation with prerequisite DTO: a task/run pair lacking receipt identity cannot construct AdmissionBinding; it remains a typed partial disposition rather than inventing a receipt.
- Header/full-decode separation: passing expiry/fingerprint preservation, mismatched header, invalid scalar and unknown-format tests. Neither clock nor incoming fingerprint is accepted. Inclusive expiry, changed-payload 409 precedence and replacement are later-consumer behavior, not claimed as B2 proof.
- JSON strictness and safe errors: passing duplicate/nonobject/bare-nonfinite, lossy-number, nesting, Unicode and suppressed-chain tests. Tags and the stored fingerprint survive. Original-model fingerprinting, actual evidence-json serialization, model_of/model_of_json materialization, arbitrary permitted program_context end-to-end and Run JSONB object insertion are UNVERIFIED: handwritten tag fixtures and a fixed digest do not prove those paths.
- Raw/production pool durability: UNVERIFIED. Three tests skip at `test_admission_codec.py:470` for missing DSNs. No disposable migration-chain/downgrade execution, DB session identities, final SQL counts, or real authorized principal/Workspace/Project/registered Graph proof is claimed. Prior DB claims are not substituted for fresh evidence.
- Reachable production behavior: absent. Source import search finds only codec-to-identity imports and the Vulture enum whitelist. `admission_codec.py:50-53` explicitly records the missing consumer. Tests/exports do not establish runtime reachability. Wiring production solely to silence the gate violates the leaf's activation boundary.
- Stage constraints: no live _assess, scope utility, HTTP/queue response, admission decision, deletion or metadata policy changes. External coordination/activation release remains UNVERIFIED; assignment permits this local repair audit only.
- Common validation/inventory: focused tests, Ruff, format, scoped mypy, Vulture and inventory pass. Mandatory provenance fails. Full unchanged integration CI and pre-fix/mutation proof are UNVERIFIED; no code/test repair was made in this round.

## Handoff

BLOCKED. Only changed file: this report. Preserve all existing implementation, tests and ledgers. Commit locally; no push or GitHub actions.

The mandatory gate at `.github/workflows/vulture-ratchet.yml:77` rejects entries in `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`. The supplied Vulture exception does not authorize reachability grants or activation. Resolving this requires owner-approved integration/consumer evidence or a separately landed authority change reconciled with #1893's explicit no-grant constraint, not another candidate-side ledger edit. No merge conflict was observed; no remote re-enumeration or speculative sync was performed.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker). Next: provide changed trusted-base/authorized consumer evidence and the candidate-qualified failing CI test traceback. Repeating an unchanged-input repair cannot resolve these constraints.
