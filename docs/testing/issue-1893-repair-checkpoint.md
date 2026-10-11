# Issue 1893 repair checkpoint

## Frozen scope

- Issue: #1893 only; branch `auto-1893`.
- Starting head: `199cb878de8644c1b311106fc8acb3c75ff927c2`.
- Assigned develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Process only admission codec/identity implementation, adjacent tests and inventory notes, and the named CI gates; no runtime activation, GitHub mutation, or reachability/grant edits.
- Initial worktree clean; no incoming edits to salvage.
- Ambiguity: dispatch names `test: failure` without a failing node. Proceed by reproducing focused tests and inspecting captured CI evidence, not guessing a repair.

## Supplied evidence (not independently reproduced yet)

Job `cc7990c95b7b426e9409f5d64eeadbb3`: check-0 dependency sync succeeds; check-1 ruff succeeds; check-2 format succeeds (3277 files); check-3 reports 201 passed, 3 skipped; check-4 inventory succeeds (16466 core nodes). Skipped PG legs do not establish durability.

## Independently reproduced checkpoint

At the starting source SHA, with 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings, zero unclassified; no Vulture amendment justified.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both admission modules add unauthorized unreachable identities and dispositions (169 trusted entries versus 171 candidate entries).
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: 201 passed, 3 skipped (PG environment absent).

The previous blocker is real at this exact head, not an unbanked Vulture finding. No permitted candidate-side ledger edit can resolve trusted-base authorization. Final disposition: **BLOCKED**. No speculative code or ledger repair is justified.

## Remaining executed validation

All commands below completed successfully with a 1200-second command timeout:

- `uv run ruff check .`
- `uv run ruff format --check .` (3277 files)
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` (two files)
- `uv run python scripts/check-shipped-surface-truth.py`
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` (16466 collected nodes, zero duplicate evidence)
- `git diff --check`

`rg -n 'admission_codec|runs.admission_identity' packages/*/src` found only the codec's DTO import and a Vulture whitelist import, not a production consumer. Codec lines 49-52 explicitly document the inactive contract. No fake caller or package export was introduced to bypass that fact.

Parsed the frozen dispatch snapshot's check-run records (no network refresh): the failed `test` check names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null summary/text. The captured `exact-debt-ledger` failure names `9922f395daa39249991f18210a6d4da68a3a76cb`. Neither is the assigned head. The generic current-head test failure remains **UNRESOLVED** without a traceback; focused tests do not reproduce it.

## Architecture and acceptance review

Read repository instructions and accepted ADR-081226-a66b (canonical lifecycle), ADR-082526-7f02 (immutable admission provenance, Attempt-owned dispatch), and ADR-083126-5e62 (trusted-base quality authority). Reviewed codec, identity constructors, adjacent tests, migration 055 field/constraint mapping, and exact-debt-ledger workflow. Reconciliation: the legacy pair without a receipt remains partial because #1851's canonical binding requires receipt evidence; fabricating a receipt would violate the no-inference contract. No scheduler, store, authorization, HTTP, queue, assessment, claim decision, scope utility, or policy changed.

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces and six error codes | Source review and focused scalar/schema/header tests PASS |
| Strict UUID hex storage and signed timestamp validation via #1851 constructors | Focused owner/generation/header/constructor tests PASS |
| Fresh flat named mapping; immutable v2 snapshots; bound/unbound/acknowledged state | Three in-memory round-trip variants PASS; independent paired-column assertions at `test_admission_codec.py:134-137` agree with migration 055 |
| Legacy bound/unresolved/partial and receipt-only evidence, no guessed identity | Existing pairing, missing-receipt, malformed-evidence, and completed_at tests PASS |
| Header preserves expiry/fingerprint despite full-decode failures; unknown formats and mismatched headers fail closed | Both header-separation tests and format/scalar mismatch cases PASS |
| Strict TEXT JSON, no duplicate keys/nonobject roots/bare nonfinite values; safe error scope and suppressed parsing chains | Existing JSON, nesting, numeric-loss, surrogate, and diagnostic cases PASS |
| Tagged program_context evidence and stored fingerprint survive codec round trip | Tagged-nonfinite/Unicode/numeric cases PASS; tags remain objects, fingerprint unchanged |
| Evidence-json/model_of/model_of_json materialization and original-model fingerprinting | UNVERIFIED end-to-end: tests construct tags directly; this codec does not materialize task/Run models |
| Raw/production pools, real migrated DB, TEXT snapshot storage | UNVERIFIED in this round: three PG cases skipped for missing environment; prior job's PG claims are not counted as fresh proof |
| Run payload text::jsonb is an object, not a JSON string | UNVERIFIED: admission tests do not insert Run payloads |
| Authorized explicit principals, Workspace/Project, registered Graph kinds | UNVERIFIED: fixtures prove DTO representation, not authorized production admission |
| Production reachability | NOT ESTABLISHED: absent consumer and failed trusted-base gate |
| Consumer expiry/409 precedence, crash/dispatch invariants | UNVERIFIED, reserved for C/F2; not B2 decisions |
| Focused tests, lint, format, applicable typing, inventory, Vulture, shipped-surface gate | PASS as recorded above (201 passed, 3 skipped; 204 collected cases) |
| Full unchanged CI | UNVERIFIED; provenance gate independently FAILS |
| Coordination and activation constraints | Repair-only assignment observed; activation remains blocked |

## Handoff

Only this report changed in this round. No tests added or changed, so no inventory delta/note is required. No mutation/pre-fix experiment is claimed for unchanged code. No PostgreSQL durability, session identities or SQL residue counts are claimed in this round. No fetch, merge, push, GitHub mutation, or activation was performed; the clean starting worktree had no sync conflict.

Required next action: resolve the trusted-base prerequisite through the existing owner-controlled authorization/integration process. The Vulture exception does not authorize reachability-ledger/grant changes; merging the identical assigned base cannot fix it. Supply a failing current-head test traceback if a separate test repair is required. Do not redispatch the unchanged source as an unbanked-Vulture repair.

Progress: checked 1 issue, done 0 code repairs (evidence handoff complete), skipped 0 issues, errors 1 required gate; next: prerequisite owner resolution, then remaining integration acceptance and unchanged CI. Local commit is a handoff, not integration approval.
