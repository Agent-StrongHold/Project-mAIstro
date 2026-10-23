# Issue #1893 repair — job 27eec7f0

## Frozen scope and initial evidence

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Initial clean HEAD: `eec027cc75637affbdc9c419154e5603c24a100b`.
- Fixed comparison base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Single item: #1893 codec repair; no other issues/PRs are dispatched.
- Files to inspect: `AGENTS.md`, `CLAUDE.md`, relevant accepted ADRs; admission codec/identity modules and adjacent tests; existing B2 inventory note; exact-debt-ledger workflow/gate and its ledger evidence. Only this report is planned to change unless a concrete scoped defect is reproduced. No grant/reachability ledger modification is authorized.
- Dispatch snapshot declares `complete_for_scope: true` and contains the full #1893 body; the previous missing-dispatch blocker is resolved for this job.
- Driver logs inspected: check-0 dependency sync passed; check-1 ruff passed; check-2 format passed (3301 files); check-3 324 passed / 3 skipped; check-4 suite inventory passed (16543 collected identities).
- Ambiguity: the generic CI `test: failure` has no failing node in the supplied driver logs. Proceed with targeted codec/identity tests and exact requested gates, not guessed scanner repairs. Historical success claims are not current proof.

## Independently reproduced blocker

- Assigned base resolved successfully before use.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unauthorized unreachable modules and dispositions (169 trusted modules vs 171 candidate modules). All other wrapper subgates pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed identities / 1322 findings, zero unclassified or never-allowlist. No Vulture amendment is warranted.
- Read accepted lifecycle ADR-081226-a66b, immutable admission provenance ADR-082526-7f02 and trusted-base governance ADR-083126-5e62. Reconciliation: admission DTOs are not execution/authorization authority; candidate ledger edits cannot grant their own reachability exception.
- Inspected prior result artifact (625738a2): it reported the same blocker, but the commands above independently reproduce it at this assigned source SHA.

## Focused validation results

All commands below ran locally against the starting source SHA, with only this report changed:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, 2 files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: 324 passed, 3 skipped (327 collected), 1.87s. The three skips explicitly require `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: 1919 passed, 310 skipped (2229 collected), 5 warnings, 50.65s. Warnings concern aiosqlite worker threads encountering closed event loops in `test_sqlite_store.py`, not failing codec assertions; no unrelated repair made.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16543 collected nodes, zero duplicate identities or byte-identical test files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Production import search across package Python excluding tests finds only `admission_codec.py:67` importing the identity module and `_vulture_whitelist.py:105` importing `AdmissionAssessment`. No codec production consumer was found; its own docstring (`admission_codec.py:50-53`) explicitly records the inactive contract boundary. The failing reachability gate independently agrees.

No test was added or modified, so there is no inventory delta. Historical inventory notes remain historical rather than being rewritten as fresh proof. No pre-fix/mutation failure is claimed: no concrete codec regression was reproduced. The generic hosted `test: failure` remains UNRESOLVED without a failing-node log for this head; the focused and adjacent runs above do not reproduce it.

## Acceptance audit

| Criterion | Executed evidence and limitation |
| --- | --- |
| Shared interfaces, frozen/slotted header, exact DTOs and fresh flat mapping | Inspected `admission_codec.py:127-299`; focused tests exercise all three interfaces and fresh mapping isolation. No positional SQL-row decoding. |
| Strict UUID hex, signed timestamps, supported schema/format, header-row match | Focused tests pass for noncanonical/nil UUIDs, bool/float versions, unknown formats, missing columns, invalid scalars and scalar/header disagreement. |
| Immutable snapshots and paired v2 binding | Three-state pure round trips independently assert `task_id=receipt_id` and paired Run columns, rather than only asserting encoder/decoder agreement; identity constructor enforces binding/envelope receipt agreement. Live migration constraint proof is UNVERIFIED this round. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run evidence | Focused bound, unbound, one-sided pair, receipt-only, missing receipt and malformed/whitespace identity cases pass. Both legacy IDs without a receipt remain partial because the prerequisite DTO requires explicit receipt identity; fabricating one is prohibited. |
| Header evidence survives snapshot/binding failure; no clock or decision | Expired-header, malformed-snapshot expiry preservation and partial-binding fingerprint preservation tests pass. Source takes no clock/request fingerprint and makes no claim, expiry, assessment, HTTP or queue decision. Consumer replacement/409 ordering is outside B2 and UNVERIFIED. |
| Strict TEXT snapshots and safe typed failures | Duplicate/nonobject/bare nonfinite/overflow/predecoded snapshots, deep nesting, lossy decimal and UTF-8 corruption tests pass; messages omit private input and suppress parsing chains. |
| Tagged evidence and unchanged stored fingerprint | Tagged nonfinite and Unicode/numeric tests pass for stored-byte evidence. Fixture hashes/tags do NOT prove original-model fingerprinting, `encode_evidence`, `model_of`/`model_of_json` materialization or arbitrary permitted context through production admission; those remain UNVERIFIED end to end. |
| Real migrated PostgreSQL with raw and production pools | UNVERIFIED: all three codec database cases skipped for absent DSNs. No disposable DB was provisioned, no migration/session identity/final SQL counts are claimed. Run JSONB object-vs-double-encoding acceptance is also UNVERIFIED. |
| Explicit principals, authorized Workspace/Project and registered Graph kinds | UNVERIFIED through production admission: codec fixtures are representation-only identity strings, not authorization or registered-Graph evidence. No fake runtime caller added. |
| Required CI and honest runtime reachability | Ruff, format, scoped mypy, Vulture, inventory, shipped-surface and scoped tests pass. Required trusted-base provenance FAILS for two modules and their dispositions. Full unchanged integration CI is UNVERIFIED. Passing provenance subgates include promotion-surface; they do not override the reachability failure. |
| Scope, coordination and canonical execution | Report-only change preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`; no new scheduler, Goal/event authority, authorization path, activation or legacy/deletion policy. Ownership/activation choices remain a coordination boundary, not an implied approval. |

## Committed handoff

**BLOCKED**, not merge-ready. `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` fail the required provenance step in `.github/workflows/vulture-ratchet.yml:77`. No production activation, new caller, SQL mutation, or identity inference is authorized by this leaf. The reproduced trusted-base blocker cannot be repaired using the Vulture-only exception.

Required next action is a separately reviewed trusted-base authorization/coordination decision (two-merge rule), or an explicitly authorized actual consumer integration outside B2. This worker must not modify reachability grants/ledgers or invent a caller to make the slice green. Also obtain the actual CI failing-node log before further test repairs. Repeating the same candidate-side Vulture amendment cannot resolve this blocker.

Changed file: `docs/testing/issue-1893-repair-27eec7f0.md` only. No code, tests, gates, grants or ledgers changed; no GitHub mutations. Residual risks are the required provenance failure, unexecuted live PostgreSQL and end-to-end materialization acceptance, and absent original failing-test evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base authorization/coordination and failing-node evidence}`. This is a local handoff, not integration, activation or issue-closure approval.
