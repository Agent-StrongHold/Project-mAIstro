# Issue #1893 repair validation

## Frozen scope

- Assigned item: #1893 only, branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `b6617c653ba07e02465e3469a861ed5e47a0bd2e`; supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Working tree was clean. No incoming work required salvage.
- Scope: existing admission identity/codec implementation, adjacent tests and inventory notes, relevant ADRs, CI test/provenance/vulture evidence, and this report. No unrelated issues or PRs will be processed.
- Ambiguity: generic `test: failure` has no failing test attached. Proceed by inspecting supplied evidence and reproducing focused acceptance and named gates; do not invent repairs or edit non-vulture ledgers.

## Initial evidence

Read repository instructions. Supplied job check logs: dependency sync successful; lint passed; format passed (3301 files); focused pytest 312 passed/3 skipped; core inventory passed (16541). These are driver evidence, not independent proof of acceptance. Further validation results follow.

## Independently reproduced blockers

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings, 0 unclassified. No Vulture amendment warranted.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions absent from trusted-base authorization. The permitted Vulture exception cannot repair this. No develop-sync conflict exists.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py -x -q`: FAIL, 6 passed/1 failed. Line 138 requires contiguous `not a valid extension lock`; actual output wraps after `not`. Invalid lock still exits 1 and reports the correct diagnostic. This is evidence of a fragile unrelated CLI assertion, not a codec failure; left unchanged under the codec-only assignment. The unnamed remote test failure is not conclusively identified by this local reproduction.
- Prior result artifact inspected. No prior acceptance claims are adopted as fresh execution evidence.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: 312 passed, 3 PostgreSQL cases skipped because DSNs are unset. No database durability claim from this run.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS (16541 nodes; no duplicate evidence). No test additions or inventory delta this round.
- Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Preserve canonical execution ownership and immutable admission provenance; candidate bookkeeping cannot authorize its own reachability expansion. No conflicting issue policy is implemented.
- `rg -n 'admission_codec|admission_identity' packages/*/src --glob '*.py'`: only codec -> identity and Vulture whitelist -> identity imports. No reachable production codec consumer found; codec lines 50–53 explicitly state inactivity.
- `uv run python scripts/check-reachability.py`: PASS (1403 modules, 171 unreachable). `uv run python scripts/check-reachability-dispositions.py`: PASS (50 groups). `uv run python scripts/check-shipped-surface-truth.py`: PASS. Candidate-ledger checks do not override trusted-base rejection.
- `git diff --check`: PASS.

## Acceptance audit at starting HEAD

The full codec and identity modules and codec tests were inspected. All execution above is against `b6617c653ba07e02465e3469a861ed5e47a0bd2e`; only this report changes this round.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact APIs; frozen/slotted header; #1851 constructors; fresh flat mapping | Focused codec/identity tests pass, including round trips and fresh mapping mutation isolation. Source confirms pure DTO signatures. |
| Named columns, UUID .hex only at storage, signed timestamp validation, matching scalar header | Focused mismatch, unsupported schema/format, strict UUID, scalar range and binding-shape cases pass. Actual SQL round trip UNVERIFIED this round. |
| Six typed error codes, validated scope only, safe errors and suppressed parser chains | Focused invalid snapshot/header/record/partial evidence tests pass, including private values, deep nesting and surrogate injections. |
| Legacy bound/unresolved/partial/receipt-only/announced-without-Run, no inferred identity | Focused legacy cases pass. Both task/run without receipt deliberately remain partial: canonical binding requires receipt evidence and guessing is forbidden. completed_at grants no authority. |
| Header remains useful despite snapshot/binding corruption; unknown formats fail closed | Named expiry/fingerprint preservation and unknown-format tests pass. No clock, incoming fingerprint or assessment decision exists in this module. C/F2 replacement/409 precedence UNVERIFIED (outside this leaf). |
| Canonical TEXT snapshots, duplicate/nonobject/bare nonfinite rejection, permitted evidence and fingerprint preservation | Focused canonical/Unicode/number/tagged snapshot tests pass. Fixtures supply tags and fingerprints; they do not prove the original model -> fingerprint -> evidence-json -> model_of/model_of_json integration. That production path is UNVERIFIED. |
| Same migrated disposable PostgreSQL database, raw/production pools, durable rows and session identities | UNVERIFIED this round: all three database cases skipped. Earlier live DB claims are not reused. No new database, migration, downgrade, row-count or session evidence claimed. |
| Run JSONB object (not doubly encoded), explicit authorized principals/Workspace/Project/Graph | UNVERIFIED: these tests exercise representations, not authorized admission or canonical Run inserts. |
| No SQL mutation/HTTP/queue/live assessment/scope/activation/policy change; canonical execution ownership retained | Source inspection confirms pure mappings/DTOs; this round makes no executable changes. Goal -> Graph -> Run -> NodeRun -> Attempt preserved. |
| Focused tests, lint/format, scoped mypy, truthful inventory | PASS as above, except explicitly skipped PG cases. No tests added and no inventory delta required. No mutation/pre-fix claim because no implementation repair was made. |
| Runtime reachability, unchanged required integration CI, no ledger edits to hide unwired code | BLOCKED: trusted-base provenance rejects existing admission ledger additions. No reachable production codec consumer. Full integration CI UNVERIFIED; scoped CLI test reproduces an unrelated failure. No ledger, grant or gate edited. |

## Handoff

Changed file: `docs/implementation/issue-1893-repair-validation.md` only. No justified in-scope executable repair emerged; Vulture has no unbanked identities. Do not retry the same candidate-ledger checks expecting authorization to change. The owner must coordinate either separately landed trusted-base authority or the actual authorized consumer before this branch can pass provenance. The unrelated CLI assertion requires its own scoped repair; the exact remote failing test still needs a log.

No production activation, GitHub mutation, push, fetch, merge, destructive git command, or issue closure. This evidence will be committed locally. Residual risks are all UNVERIFIED rows above; this is not merge/integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 2, next: owner-coordinated provenance resolution and separately scoped CLI-test repair}`.

