# Issue 1893 repair checkpoint

## Repair recheck: job a6cc447b4c2e411a872eca70d0e6e2dd

Frozen scope: #1893 only, assigned `auto-1893` worktree, clean starting HEAD
`7a6b87b5bd38f5bcfb4cb55f35a35d0aeea572a7`. Supplied base and resolved local
`origin/develop` both equal `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
No sync conflict, remote refresh, GitHub mutation or production activation.
Read repository instructions, frozen dispatch issue/check evidence, driver
check-0..4 logs, prior result, codec/identity implementations and codec tests,
and accepted ADRs 082526-7f02, 082826-b601 and 062. Preserve immutable admission
provenance and `Goal -> Graph -> Run -> NodeRun -> Attempt`; a fake consumer or
alternate execution authority is not an acceptable reachability repair.

### Fresh validation at the starting source SHA

Commands used 1200-second timeouts; logs are `worker-*.log` in
`/home/dev/maistro/jobs/a6cc447b4c2e411a872eca70d0e6e2dd/`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 reviewed identities/findings, zero unclassified. No amendment is
  warranted; Vulture authorization cannot authorize reachability ledger edits.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`:
  **FAIL, exit 1**: both admission modules and their dispositions are NEW and
  unauthorized against the trusted base (169 -> 171); other sub-ratchets pass.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **845 passed, 20 PG-gated skips**, 865 cases. Skips are not durability proof.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16567 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`,
  `uv run python scripts/check-reachability.py` and
  `uv run python scripts/check-reachability-dispositions.py`: PASS. Candidate
  ledger agreement does not override the failed trusted-base authorization.

### Fresh PostgreSQL evidence

Created new disposable DB `repair_1893_a6cc447b` on the existing
`maistro-postgres` PostgreSQL 18.6 container (host port 5433). Creation succeeded
without reuse. Nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` all targeted that DB; `MAISTRO_REQUIRE_PG_LEGS=1`.
Credentials were read from container configuration and not printed or recorded.

- `uv run alembic upgrade head`: PASS, real empty -> 001 -> ... -> 063 chain,
  including migration 055. No stamping, SQLite recreation or downgrade test.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs -o junit_family=legacy --junitxml=<job>/worker-pg.xml`:
  **204 passed, zero skipped**, including three real raw/production pool cases.
- Independent production/raw PID pairs: unbound 373488/373489, bound
  373490/373491, acknowledged 373492/373493. All identify this same DB at
  `172.20.0.2/32:5432`; each case asserts one persisted admission row.
- Final SQL audit: revision 063, `task_idempotency=0`, `canonical_runs=0`.
  DB retained for audit; session properties and counts are in `worker-pg.xml`
  and `worker-pg-audit.json`. These are codec storage tests, not Run admission.

### Acceptance and remaining limits

| Criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces/six codes, signed timestamps, strict storage UUID hex, shared constructors | Source review and focused header/schema/scalar/owner/generation/identity tests PASS |
| Fresh flat named SQL mapping; snapshot bytes and bound/unbound/acknowledged states | Focused round trips and live migration-055-constrained INSERT/read/decode PASS |
| Legacy bound/unresolved/partial/receipt-only without inferred identity | Focused binding/whitespace/missing-receipt/completed_at tests PASS; missing receipt stays partial rather than fabricated |
| Header retains expiry/fingerprint despite snapshot or binding errors; mismatched headers and unknown formats rejected | Header-separation/scalar-mismatch/format tests PASS; codec takes no clock or request fingerprint |
| Strict TEXT JSON; duplicate/nonobject/bare nonfinite rejection; safe messages/chains and validated scope | JSON/nesting/precision/Unicode/error tests PASS, including corrupt TEXT through both real pools |
| Tagged arbitrary program_context evidence and stored fingerprint preserved | Tag/Unicode/exact-number cases PASS; no tag decoding or fingerprint recalculation in codec |
| Same migrated DB and independent raw/production JSON-codec pools | Three real cases PASS with session/row evidence above |
| Evidence-json model materialization, original-model fingerprinting and Run JSONB object rather than string | UNVERIFIED end-to-end: fixtures build tags directly and do not insert canonical Runs |
| Authorized explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED as admission: DTO fixture identity strings do not establish authorization |
| Production reachability and full required integration CI | NOT PROVEN: only codec-to-DTO and whitelist imports found; provenance FAILS; full integration CI not rerun |
| Consumer inclusive expiry/409 precedence, crash/dispatch/claim invariants | UNVERIFIED; reserved for C/F2, outside this representation-only leaf |
| No SQL mutation, HTTP/queue/scope utility, live assessor or admission-policy changes | Preserved; this round changes this checkpoint only |

The frozen check-run snapshot reports `test: failure` at sibling head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null summary/text. Its captured
`test` at `80171ce1cff9ca45eaf000bf52569875643a5ba0` passes while
`exact-debt-ledger` fails. Neither is current-head CI evidence. The supplied
generic test failure remains UNRESOLVED, not repaired by passing focused tests.
No source/test repair or pre-fix/mutation experiment is claimed; no tests changed,
so no inventory delta or new inventory note is necessary.

**BLOCKED.** Preserved unauthorized entries remain at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`; CI requires the failing gate
at `.github/workflows/vulture-ratchet.yml:77`. Resolving the trusted-base
prerequisite requires owner-controlled authorization/integration outside this
lane. Re-running unchanged source or amending Vulture cannot resolve it.
No ledger/grant/gate changes are justified or made. Only this existing report
is committed locally as an evidence handoff, not integration approval.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required gate. Next: trusted-base prerequisite resolution and, if a distinct
test repair is required, an actual current-head failing traceback.

## Repair recheck: job 6fbc3c17552a4262828dec6dabe9c0ab

Frozen scope: #1893 only, assigned worktree `/home/dev/Git/wt/auto-1893`,
branch `auto-1893`, initially clean source
`d79757c4f621b097a5fec76689776a533df12fcf`. Assigned target and local
`origin/develop` both resolve to `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`;
`git merge-base HEAD 321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62` resolves to
`2154f845347c9541016288c760f8da3f5cd2e064`. The gate uses that merge base,
not the target tip, as its trusted comparison. No unresolved merge or incoming
work was present. No fetch, merge, remote mutation, or source deletion performed.

Read repository instructions, frozen issue body, supplied check-0 through
check-4 logs, prior result, codec and identity implementations and adjacent
tests, binding-repair inventory note, exact-debt-ledger workflow, and accepted
ADRs 081226-a66b, 082526-7f02 and 083126-5e62. The stage restriction remains:
typed representation is not admission authority or production activation.
Canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`, immutable admission
provenance and trusted-base authorization must not be bypassed to make this
inactive leaf green. A legacy pair without receipt evidence stays partial;
fabricating a receipt to satisfy the shared DTO would violate no-inference.

### Fresh execution

All validation commands used a 1200-second timeout. Logs are under
`/home/dev/maistro/jobs/6fbc3c17552a4262828dec6dabe9c0ab/worker-*.log`.
Earlier claims are not counted as this round's execution.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1322 findings / reviewed identities, zero unclassified and zero
  never-allowlist findings (`worker-vulture.log`). No ledger amendment is
  warranted. The Vulture exception does not authorize reachability edits.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`:
  **FAIL**, exit 1 (`worker-provenance.log`). Both admission modules are NEW
  unauthorized unreachable identities and dispositions, 169 trusted versus
  171 candidate entries. All other provenance sub-gates pass.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s`:
  **324 passed, 3 skipped**, 327 cases, 1.62s (`worker-focused.log`). The
  three skips are real-pool contrasts at `test_admission_codec.py:470`:
  required PostgreSQL environment is absent. Skips are not durability proof.
- `uv run ruff check .`: **PASS** (`worker-ruff.log`).
- `uv run ruff format --check .`: **PASS**, 3301 files (`worker-format.log`).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  **PASS**, two files (`worker-mypy.log`).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  **PASS**, 16543 collected nodes, zero duplicate evidence (`worker-inventory.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: **PASS**
  (`worker-shipped-surface.log`).
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src`:
  only codec-to-DTO and whitelist imports; no production consumer. Codec
  lines 49-52 explicitly describe that boundary.

### Acceptance evidence and limits

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header, required signatures and six error codes | Source review; focused header/schema/scalar tests PASS |
| Strict UUID hex, signed timestamps and shared constructor validation | Focused owner/generation/scalar/constructor cases PASS |
| Fresh flat named SQL mapping, immutable snapshots, optional binding | Three in-memory round-trip states PASS; independent task_id/run_id assertions at test lines 134-137 |
| Legacy bound/unresolved/partial/receipt-only evidence without invented identity | Focused binding, missing receipt, whitespace and completed_at tests PASS |
| Header preserves expiry/fingerprint across decode errors; mismatched/unknown formats fail closed | Header-separation and format/mismatch cases PASS; no clock or decision implemented |
| Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection and safe diagnostic chains | JSON, nesting, lossy numbers, surrogate and error-scope cases PASS |
| Tagged nonfinite and arbitrary permitted program_context evidence; stored fingerprint unchanged | Focused tag/Unicode/exact-number tests PASS; codec does not decode tags or recompute fingerprints |
| Production evidence-json/model_of/model_of_json materialization and original-model fingerprinting | UNVERIFIED end-to-end; fixtures construct tags directly, codec does not materialize models |
| Raw/production pools against the same real migrated DB; SQL/session/identity counts | UNVERIFIED this round: three PG skips, no DB was provisioned; prior PG claims not adopted |
| Run text::jsonb payload is an object; authorized principals/Workspace/Project/Graph | UNVERIFIED: DTO fixtures establish neither Run persistence nor authorization |
| Production reachability and unchanged full required CI | NOT PROVEN: no consumer and required provenance gate FAILS; full integration CI not run |
| Consumer inclusive expiry/409 precedence, crash/dispatch and claim atomicity | UNVERIFIED and outside B2, reserved for consumer/integration leaves |
| No SQL mutation, HTTP/queue/scope utility, live assessment, policy or execution authority change | Source review; this round changes only this checkpoint |

The supplied deterministic checks all pass (including 324 passed / 3 skipped)
and provide no failing test traceback. Bounded extraction of the frozen dispatch
check-run records (`worker-captured-checks.json`) finds the failed `test` at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null summary/text, not this
source. The captured `test` at `90d4c278e6d729d41a3f30d9f17bc65025d6f59d`
passes while its `exact-debt-ledger` fails. No network refresh was performed.
The generic `test: failure` is not reproduced by focused execution. No
speculative scanner fix or cosmetic source change is justified. No pre-fix/
mutation failure is claimed for unchanged code. No tests changed, so no
inventory delta or new inventory note is needed. `git diff --check` passes.

The preserved blocked entries are `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:606-613`. CI requires the failing
provenance gate at `.github/workflows/vulture-ratchet.yml:77`.

**BLOCKED**: this is an evidence handoff, not merge approval. The actual failure
requires owner-controlled trusted-base authorization/integration resolution,
not another Vulture scan or candidate-side reachability/grant edit. Do not
activate the C consumer or manufacture imports in this leaf. Supply an actual
current-head test traceback if a distinct code repair is expected. Only this
existing checkpoint is changed and will be committed locally.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required gate; next: prerequisite owner resolution and remaining integration
acceptance. No issue closure or GitHub mutation.

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
