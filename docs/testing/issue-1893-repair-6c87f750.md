# Issue #1893 repair — job 6c87f750

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `0ea8e151817ee1bf14312ad8271094701ba21df6`; supplied develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Initial worktree clean. No incoming edits require salvage.
- Inspect existing codec, identity DTOs, their adjacent tests, repository instructions, relevant ADRs, and exact CI gate commands. Only planned write is this evidence note unless an actual in-scope defect is reproduced.
- No GitHub mutations, production activation, reachability grants, or policy changes. Vulture ledger amendment permitted only if the required scan demonstrates retained unbanked identities.

## Initial evidence and ambiguity

Driver logs inspected in `/home/dev/maistro/jobs/6c87f7509a35467b8ba1abb334076c64`: check-0 dependency sync succeeded; check-1 ruff passed; check-2 3301 files formatted; check-3 346 passed / 3 skipped; check-4 suite inventory 16567 nodes passed. These are driver evidence, not execution claimed by this worker.

Dispatch supplies only `test: failure`, no failing node or traceback. Assumption: reproduce focused acceptance and named debt gates before making any code repair. Historical claims are not accepted as new validation. The immutable dispatch snapshot supplies issue/PR evidence; no re-fetch or re-enumeration is planned. Staged B2 readiness is separate from production activation and merge approval.

## Confirmed blocker

The supplied base resolves and equals `git merge-base HEAD <base>`. Fresh exact Vulture scan passes: 1322 reviewed identities / 1322 findings, zero unclassified. No ledger amendment is warranted.

Fresh `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` exits 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions lacking already-landed authorization (four violations). Logs: `.pytest_cache/repair-6c87f750/{vulture,provenance}.log`. This confirms the prior blocker independently; it is not a Vulture finding or a sync conflict.

Read repository AGENTS.md and accepted ADRs 081226-a66b, 082526-7f02, 082826-b601, 083126-5e62. Reconciliation: preserve immutable admission provenance and canonical Goal -> Graph -> Run -> NodeRun -> Attempt; do not activate an unauthorized consumer or add fake imports to pass reachability. Candidate ledger edits cannot authorize themselves. The permitted Vulture repair does not authorize reachability policy edits.

## Executed validation

Commands below ran at the starting source SHA with 1800-second command timeouts. Full local ignored logs are under `.pytest_cache/repair-6c87f750/`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 reviewed identities, no unclassified findings |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL exit 1: four reachability/disposition authorization violations |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 349 nodes: 346 passed, 3 skipped |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 2229 nodes: 1919 passed, 310 skipped, 6 warnings |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16567 nodes, zero duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

Adjacent warnings are aiosqlite worker-thread closed-event-loop warnings; no evidence ties them to the unspecified hosted failure. Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` are unset. No live database execution, session identity or residue count is claimed. Database setup was not pursued after confirming the independent authorization blocker.

Production-source import search (`rg -n 'admission_codec|admission_identity' packages --glob '*.py' --glob '!**/tests/**'`) finds only the codec's identity import and the Vulture whitelist. There is no production codec consumer. Test imports are not runtime reachability.

## Acceptance assessment

Inspected the complete codec, identity DTO module and their two test files. Passing tests establish the staged library contract, not admission activation.

| Criterion | Evidence / limitation |
| --- | --- |
| Exact header/record/encode interfaces; frozen/slotted header; strict named scalar fields and storage UUID hex | Source and passing scalar, format, UUID, missing-column and DTO immutability tests |
| Header/row match and preserved expiry/fingerprint despite invalid full records | Passing scalar-mismatch tests and named header-preservation tests; no clock or incoming fingerprint argument |
| V2 immutable records, fresh flat SQL mappings, snapshots and binding identities preserved | Three-state round trips, fresh mapping assertions, receipt/binding identity tests; independent migration-055 shape assertions at `test_admission_codec.py:134-137` |
| Legacy bound/unresolved/partial distinctions, no guessed identity | Passing pair, receipt-only, missing-receipt, unreadable/whitespace identity and ignored-completed-at tests; canonical binding requires actual receipt evidence, not task-id inference |
| Six typed failures; validated scope only; no unsafe parsing-chain disclosure | Source enum/error review and passing corrupt snapshot, nesting, numeric loss, Unicode, scope and token tests; suppressed exception chains |
| Strict TEXT object JSON; duplicate/nonobject/bare nonfinite rejection; tagged evidence and stored fingerprint preservation | Passing JSON rejection and tagged nonfinite round trips; stored corrupt TEXT injected directly into row mappings, not mocked transaction results |
| Existing evidence-json/model_of materialization and original-model fingerprinting; arbitrary permitted program_context | UNVERIFIED end-to-end: fixtures use synthetic tagged JSON and predetermined fingerprints. Storage preservation is proven, production-model integration is not |
| Disposable migrated PostgreSQL; raw/production pool contrast; actual TEXT bindings and JSONB Run object | UNVERIFIED this round: all three pool tests skipped; no migration, real SQL row-count or Run INSERT evidence claimed |
| Authorized explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED production admission: synthetic DTO identity strings do not establish authorization |
| No SQL mutation, HTTP/queue changes, expiry/mismatch classifier, live assessment, scope utility or policy changes | Codec is Mapping-to-DTO conversion; this round changes only this report. Consumer expiry/409 precedence remains outside B2 |
| Inventory, lint, format, mypy and integration quality gates | Above focused commands pass except trusted-base provenance. Full unchanged integration CI and standalone promotion/reachability commands UNVERIFIED this round; provenance promotion subcheck passes |
| Coordination, inactive-stage constraints and reachable production behavior | Assigned head/base verified; no activation attempted. Independent mergeability remains BLOCKED by trusted-base authorization |

No tests or source code changed; inventory delta is zero, so no new inventory note is required. No new pre-fix/mutation experiment is claimed. No observed in-scope source defect justifies speculative repair.

## Final handoff

**BLOCKED.** `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` add the two modules without trusted-base authorization. The failing command is mandated at `.github/workflows/vulture-ratchet.yml:77`. Vulture permission cannot repair reachability policy. No sync conflict exists, so no fetch/merge was needed.

Hosted `test: failure` is **UNRESOLVED**: focused and adjacent tests pass; the dispatch provides no failing node/traceback. Full integration CI remains unverified. Need its exact command, tested SHA and traceback before repairing source.

Only changed file: `docs/testing/issue-1893-repair-6c87f750.md`. Commit this evidence handoff, not merge/activation approval. No source, test, ledger, grant or gate edits; no GitHub mutations.

Progress: checked 1, done 0 repairs, skipped 0 items, errors/blockers 1. Next: integration owner resolves the trusted-base authorization dependency outside this lane and supplies actual hosted failure evidence. Re-running the unchanged state as a Vulture repair cannot resolve this blocker.
