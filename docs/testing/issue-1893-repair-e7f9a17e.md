# Issue #1893 repair — e7f9a17e

## Frozen scope

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `90d4c278e6d729d41a3f30d9f17bc65025d6f59d` (verified clean).
- Supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inspect the existing admission codec, immutable identity constructors, adjacent tests,
  applicable ADRs, CI workflows and supplied dispatch/check artifacts. No other issue
  or PR will be processed. Intended edit: this evidence/handoff note; change code or
  tests only for a reproduced defect within #1893. No reachability/grant edits.
- Role ambiguity resolved as writer (explicit lane repair assignment). The vulture
  ledger exception is limited to reproduced vulture debt, not reachability grants.
- Supplied check logs: sync, ruff, formatting and suite inventory passed; focused
  tests report 312 passed / 3 skipped. These do not establish live PostgreSQL evidence.
- Prior result reports unauthorized reachability entries and no reproduced test
  failure. These claims require fresh validation, not assumption.

## Results

- Fresh Vulture CI command: PASS, 1322 reviewed findings, zero unclassified or
  never-allowlist identities. No Vulture ledger change is justified.
- Fresh `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run
  python scripts/check-ratchet-provenance.py`: FAIL (exit 1). The supplied base
  resolves. Both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are new unreachable modules and new dispositions
  without already-landed authorization. Other provenance subgates pass.
- This reproduces the previous blocker on the assigned base. It is neither a
  Vulture failure nor a develop-sync conflict. The Vulture-only ledger exception
  cannot authorize reachability edits. No activation or fake consumer is allowed.

- Fresh `uv sync --locked --extra dev`: PASS.
- Fresh `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: PASS,
  312 passed / 3 skipped, 315 collected, 1.48s. PostgreSQL cases skip at
  `test_admission_codec.py:470` because both DSNs are absent.
- Fresh `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  3301 files already formatted.
- Fresh `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- Fresh `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Fresh `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16541 nodes, zero duplicate identities or
  byte-identical files. No tests changed; no inventory delta needed.
- Fresh `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: PASS, **15468 passed, 1070 skipped,
  3 xfailed, 61 warnings in 238.40s**. Log:
  `/tmp/1893-e7f9a17e-core-pytest.log`. Warnings include aiosqlite threads
  encountering closed event loops. The reported `test: failure` was not
  reproduced in the changed package; cross-package CI was not run.
- Source import search finds only codec-to-identity import and Vulture whitelist
  usage, not a production consumer. `admission_codec.py:50-53` explicitly records
  inactive status. Test imports are not production reachability evidence.
- Read repository instructions, documentation authority map, and accepted
  ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62. Reconciliation: preserve
  Goal -> Graph -> Run -> NodeRun -> Attempt, immutable admission provenance,
  and protected-base authorization. No candidate bookkeeping or fake caller
  can establish reachability or authorize debt.

## Acceptance audit

All executed validation above uses the starting source SHA. This round changes
only this report, not production or test behavior.

| Criterion | Evidence and limit |
| --- | --- |
| Frozen/slotted header, shared interfaces, exact immutable DTOs, fresh flat SQL parameters | Source inspection and passing header, encode, round-trip and identity tests. Named storage columns; no positional row decoding. |
| Strict storage UUID hex, signed timestamps, matching header and #1851 constructor validation | Passing UUID, scalar/header mismatch, invalid v2 and binding tests. The round-trip test independently asserts the migration-055 task_id/receipt_id/run_id shape, rather than only encode/decode agreement. |
| Legacy bound/unbound/partial without identity invention | Passing bound, unbound, one-sided, receipt-only, pair-without-receipt, unreadable-evidence and completed_at tests. Both legacy IDs without receipt evidence fail partial: the constructor requires an explicit receipt and the codec cannot invent one. |
| Header/full decoding separation; unsupported schema/format fail closed | Passing preserved expiry/fingerprint, malformed snapshot, partial binding and unknown-format tests. Consumer replacement/409 precedence remains outside B2 and UNVERIFIED. |
| Strict TEXT snapshots, safe typed error codes and validated scope | Passing duplicate/nonobject/bare-nonfinite, nesting, lossy-number, surrogate, predecoded-value and suppressed-chain tests. The codec suppresses unsafe parsing chains and does not quote raw snapshot/token values. |
| Permitted program_context tags preserved without fingerprint recalculation | Passing tagged nan/inf/-inf, Unicode and numeric evidence round trips. End-to-end original-model fingerprint -> encode_evidence -> model_of/model_of_json materialization is UNVERIFIED; these fixtures supply tags and fingerprint independently. |
| Raw/production asyncpg pools on same real migrated disposable DB | UNVERIFIED: three tests skipped because required DSNs are absent. No fresh migration, session identity, SQL residue count or Run JSONB object-shape proof claimed. |
| Explicit authorized principals, Workspace/Project, valid registered Graph kinds | UNVERIFIED as production admission. Fixture identity strings prove representation, not authorization or registered Graph admission. |
| Focused pytest, lint, format, mypy and inventory | PASS as listed above. 315 focused nodes; 16541 full core nodes. No new test or mutation/pre-fix run claimed. |
| Required CI, vulture/reachability/disposition/promotion | Vulture and shipped-surface PASS. Provenance FAILS for reachability and dispositions; promotion provenance passes within that command. Full integration CI and remaining standalone gates UNVERIFIED. |
| Reachable production behavior | UNVERIFIED: no runtime codec consumer found. The staged leaf remains inactive as explicitly required by this issue, not falsely presented as production behavior. |
| No SQL mutation, clock, assessment, HTTP/queue/scope-policy change or competing execution authority | Representation-only source; this round changes only this note. Production activation and coordination remain outside lane authority. |

## Handoff — BLOCKED

Changed file: `docs/testing/issue-1893-repair-e7f9a17e.md` only. No code repair
was justified by the executed tests; no Vulture ledger amendment was warranted.
No tests were added and no inventory count changed.

The required gate at `.github/workflows/vulture-ratchet.yml:77` rejects
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614`. Resolution requires a
separately reviewed authorization already landed on the trusted base, followed
by a coordinated integration, or an explicitly authorized real consumer change.
The current issue forbids activation and this lane cannot edit reachability
ledgers/grants. Repeating unchanged-source repair jobs cannot resolve that
policy blocker. No develop-sync conflict exists to repair.

Residual risks: the original CI failing node/log is unspecified and its failure
is not reproduced by the scoped core suite; live PostgreSQL, end-to-end
materialization, production reachability and full integration acceptance remain
unverified. This is a blocked handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-coordinated trusted-base authorization}`.
No push, PR, GitHub mutation, grant edit or destructive Git operation performed.

