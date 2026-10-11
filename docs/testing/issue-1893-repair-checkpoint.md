# Issue 1893 repair checkpoint

## Repair recheck: job 57b5d1880e88480487e08abd5148d462

Frozen item: #1893 only; clean starting HEAD
`5eae17c95659ad4db841a7b76ff8bde5771162a2`, assigned trusted base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Reviewed the supplied frozen
issue body/check records, driver `check-0.log` through `check-4.log`, repository
instructions, both implementation and test files, migration 055's mapping and
constraint, and accepted ADRs 081226-a66b, 082526-7f02 and 083126-5e62.
No previous execution claim was counted as fresh proof.

Fresh commands (1200-second timeouts):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1323 findings, zero unclassified, zero never-allowlist findings. No
  retained unbanked or eliminated identity warrants a Vulture ledger amendment.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`:
  FAIL, exit 1. Both admission modules are NEW unauthorized unreachable
  modules and NEW unauthorized dispositions (169 trusted, 171 candidate).
  All other sub-ratchets pass. Logs: `worker-vulture.log` and
  `worker-provenance.log` in the assigned job directory.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`:
  **201 passed, 3 skipped**, 204 collected cases, 1.34s. All three skips are
  the real-pool test at `test_admission_codec.py:470`: both required PG
  variables are absent. Log: `worker-focused.log` in the job directory.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16466 nodes, no duplicate test evidence.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src`: only the
  codec's DTO import and Vulture whitelist import, not a production consumer.

Acceptance rechecked against source and this execution:

- Frozen/slotted header, required signatures/six codes, strict UUID hex,
  signed timestamps, named flat mappings and #1851 constructor validation:
  source review and focused cases PASS.
- Immutable snapshot round trips, paired binding columns consistent with
  migration 055, legacy bound/unresolved/partial/receipt-only handling,
  header/full-decode separation and unknown/mismatched format rejection:
  focused cases PASS. Missing receipt evidence stays partial rather than
  inventing identity to satisfy `AdmissionBinding`.
- Strict TEXT JSON, duplicate/nonobject/nonfinite rejection, safe diagnostics,
  tagged program_context preservation and unchanged stored fingerprints:
  focused JSON, Unicode, numeric-loss, nesting and tag cases PASS.
- Evidence-json/model materialization and original-model fingerprinting:
  UNVERIFIED end-to-end; these fixtures construct tags directly.
- Real migrated PostgreSQL, pool/session identities, SQL residue counts,
  Run JSONB object persistence, authorized principals/Workspace/Project and
  registered Graph kinds: UNVERIFIED this round. Skips and DTO fixtures are
  not durability or authorization proof.
- Production reachability and unchanged full CI: NOT PROVEN. No consumer;
  provenance gate fails. Consumer expiry/409 precedence and crash/dispatch
  invariants remain UNVERIFIED and outside B2's representation-only scope.
- No clock, assessment/claim decision, SQL mutation, HTTP/queue/scope utility
  or policy change introduced. ADR reconciliation preserves the canonical
  lifecycle, immutable admission provenance and trusted-base authority.

The frozen dispatch's failed `test` check names
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this head; its summary/text are
null. The captured `test` check on `9922f395daa39249991f18210a6d4da68a3a76cb`
succeeded while `exact-debt-ledger` failed. These records do not identify a
current-head failing test to repair. That signal remains UNRESOLVED; no
speculative code or cosmetic scanner repair is justified.

Decision: **BLOCKED**. Only this checkpoint changes; no new tests or inventory
delta, no code/ledger/grant edits, no fake caller or activation, no GitHub
mutation. This is an evidence handoff, not merge approval. No pre-fix/mutation
experiment is claimed for unchanged code. Next: owner-controlled trusted-base
prerequisite resolution and a current-head test traceback if a separate repair
is needed. Do not redispatch the same source as unbanked Vulture debt.
Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required gate. Commit this checkpoint locally; remaining acceptance is explicit
above.

## Repair recheck: job df08dd8a60534fb2bdb15c22261b1cec

Frozen item: #1893 only, starting HEAD `c5f755480759b142b33543235fbf206f0fd8e0ef`,
assigned base `435dc1937e0407ab4de198ffcced49860bb14ad2`. Worktree initially
clean. Both local `origin/develop` and the merge base resolve to that assigned
base; there is no develop-sync conflict to repair. No remote refresh performed.

Read the supplied dispatch issue body, captured logs `check-0.log` through
`check-4.log`, prior result, codec and adjacent tests, and accepted ADRs
081226-a66b, 082526-7f02, and 083126-5e62. Prior passing claims were not treated
as new execution evidence. The stage restriction and ADRs remain compatible:
keep this a typed representation, preserve immutable admission provenance and
Attempt-owned execution, and do not create a fake production caller or alter
trusted-base authorization to make the inactive slice pass.

Fresh execution at this HEAD (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1323 reviewed findings, zero unclassified. No Vulture ledger amendment
  is warranted by the actual scan.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`:
  FAIL. The gate rejects both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` as new unauthorized unreachable modules and
  new unauthorized dispositions (169 trusted versus 171 candidate entries).
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`:
  204 cases, **201 passed, 3 skipped**, 1.30s. All skips are the real-pool contrast
  test at `test_admission_codec.py:470`, because both required PG variables are
  absent. No migrated-database proof, session identities, or residue counts
  are claimed in this round.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src`:
  only the DTO import within the codec and the Vulture whitelist import; no
  production consumer. The codec explicitly states that limitation at lines
  49-52. Test imports are not runtime reachability.

Acceptance review of the current source and freshly passing focused tests:

| Criterion | This round's evidence |
| --- | --- |
| Frozen/slotted header, exact interfaces, six error codes | Source review; header/schema/scalar cases PASS |
| Strict UUID hex and signed timestamps; #1851 constructors | Owner/generation and constructor rejection cases PASS |
| Named flat mapping and immutable snapshots | Three in-memory round-trip states PASS, including independent task_id/run_id assertions |
| Legacy bound, unresolved, partial, receipt-only; no invented identity | Legacy shape and whitespace/error cases PASS; absent receipt cannot be fabricated to satisfy canonical binding |
| Header survives full-decode failure; unknown/mismatched formats fail closed | Header expiry/fingerprint and mismatch cases PASS; no clock or claim decision introduced |
| Strict TEXT JSON, safe errors, arbitrary tagged evidence and unchanged fingerprint | Duplicate/nonobject/nonfinite, numeric-loss, Unicode, nesting and tag-preservation cases PASS |
| Model materialization with evidence-json/model_of/model_of_json, original-model fingerprinting | UNVERIFIED end-to-end: fixtures build tags directly; codec does not materialize task/Run models |
| Raw/production pools against real migrated schema | UNVERIFIED: three PG cases skipped, not durability evidence |
| Run payload is a JSONB object; explicit authorized principals, Workspace/Project, registered Graph | UNVERIFIED: representation fixtures do not establish these integration properties |
| Production reachability and full unchanged CI | NOT PROVEN: no consumer, trusted-base gate FAILS; generic supplied `test: failure` has no reproduced failing node |
| Consumer expiry/409 precedence, transaction/crash/dispatch behavior | UNVERIFIED and reserved for consumer/integration leaves, not implemented by B2 |
| No SQL mutation, HTTP/queue changes, assessment, scope utility or policy changes | Source review; this round changes this report only |

Additional fresh validation, all PASS (1200-second command timeout):

- `uv run ruff check .`
- `uv run ruff format --check .` (3277 files)
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` (two files)
- `uv run python scripts/check-shipped-surface-truth.py`
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  (16466 collected nodes, no duplicate evidence)
- `git diff --check`

Progress: checked 1 item, done 0 code repairs, skipped 0 items, errors 1 required
gate. Next: owner-controlled trusted-base prerequisite resolution and an actual
current-head failing test traceback if a separate repair is needed. Remaining
integration acceptance above stays explicitly unverified. This report is the
only changed file and is committed locally as a handoff, not merge approval.

Decision: **BLOCKED**, not an evidence-backed code-repair opportunity. The
Vulture exception cannot authorize edits to reachability dispositions/grants.
Owner-controlled trusted-base resolution is still required before integration;
merging the identical base or banking more candidate debt cannot resolve it.
No new tests, so no suite inventory delta. No pre-fix/mutation failure is claimed
for unchanged code. No activation, GitHub mutation, or issue closure performed.


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
