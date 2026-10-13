# Issue #1893 repair — 130db24b

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `008e3b1eaa376232399b8b0567a9c8991d35e6dd`; supplied base `2154f845347c9541016288c760f8da3f5cd2e064`.
- Only item: #1893 immutable admission codec CI repair. No GitHub mutations, activation, ownership changes, or reachability ledger/grant edits.
- Inspection scope: supplied dispatch snapshot and check logs; repository instructions and relevant ADRs; admission codec/identity implementation, adjacent tests and inventory notes; CI definitions and implicated quality gates. Edits limited to evidence-backed repair in those source/tests, its inventory note, and this report. Vulture ledger only if the explicitly requested scan demonstrates retained unbanked identities.
- Initial worktree clean. No salvage required.

## Initial evidence and assumptions

Driver logs check-0 through check-4: dependency sync, ruff check, format check pass; focused tests 324 passed / 3 skipped; core suite inventory 16543 matches. These are supplied evidence, not my executions.

Issue body explicitly stages B2 without production activation; runtime admission policy and consumer ordering belong to other leaves. I will not wire a fake consumer to satisfy reachability. Reported `test: failure` has no failing node in the prompt; reproduce focused behavior and named gate before choosing any repair. Prior findings are not assumed current.

## Validation

- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed findings, zero unclassified. No vulture ledger repair justified.
- Executed `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL. Both admission modules are new unreachable modules and new dispositions without already-landed authorization. This reproduces the prior blocker at the supplied base, independently of test behavior. No reachability edits authorized in this round.
- No MAISTRO_TEST_* environment variables configured. Three existing PostgreSQL services visible; no durability claimed yet.
- Executed `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`: **324 passed, 3 skipped**, 327 nodes. Skips are the raw/production PostgreSQL contrast in unbound/bound/acknowledged states, not durability proof.
- Executed `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3301 files).
- Executed `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- Executed `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS (16543 nodes). No tests changed or added; no inventory delta.

- Executed `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1919 passed, 310 skipped, 5 warnings**, 2229 nodes. Warnings are aiosqlite worker threads calling a closed event loop in `tests/runs/test_sqlite_store.py`; no failing node reproduced. Skips are not counted as acceptance evidence.
- Executed `uv run python scripts/check-shipped-surface-truth.py`: PASS. `git diff --check`: PASS.

## Architecture reconciliation

Read repository AGENTS.md, documentation authority hierarchy, accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), and ADR-083126-5e62 (trusted-base quality authority). The issue's staging restriction means no runtime consumer should be invented here. `admission_codec.py:51-54` and `admission_identity.py:3-7` explicitly identify these as inactive contract modules. Unit calls do not establish production admission or authorization. Current failure is trusted-base reachability policy, not unbanked Vulture identities; the narrowly permitted Vulture amendment cannot remedy it.

## Acceptance audit at the starting source SHA

| Criterion | Fresh evidence / limit |
| --- | --- |
| Frozen/slotted header, signed timestamps, strict schema/format and header-row agreement | Existing focused tests passed, including unsupported format bool/float and scalar mismatch cases; reviewed `admission_codec.py:159-258`. |
| Fresh flat encoder and immutable v2 decode, UUID hex only at storage | Existing round-trip tests passed in unbound/bound/acknowledged states; independent task/receipt column assertions present at `test_admission_codec.py:134-137`. No live SQL proof this round. |
| Legacy bound/unbound/partial distinctions without inferred identity | Existing legacy tests passed, including missing receipt, receipt-only, one-sided and unreadable identities. Constructor requires receipt identity, so a bound pair without a receipt is explicitly partial rather than inventing one. |
| Header evidence survives full decoding failure, no clock or incoming fingerprint | Existing header expiry/fingerprint tests passed; reviewed separate header and record functions. Consumer replacement/409 behavior is not implemented or proven by B2. |
| Strict object snapshots, duplicate/nonfinite rejection and safe typed errors | Existing duplicate, overflow, nested, precision-loss and surrogate corruption tests passed, with suppressed exception chain and unchanged row/header assertions. |
| Tagged permitted program_context and unchanged stored fingerprint | Existing tagged nonfinite test passed for nan/inf/-inf. Actual model_of/model_of_json materialization and Run JSONB object storage: UNVERIFIED in this round; codec itself retains snapshot TEXT rather than materializing task/Run models. |
| Raw and production-codec pools, real migration chain, session IDs and final SQL counts | UNVERIFIED: three PostgreSQL cases skipped because DSNs are absent. No destructive migration or use of an unowned DB attempted. |
| Authorized Workspace/Project, explicit principals and registered Graph kinds on positive admission | UNVERIFIED as production admission: fixtures are DTO-only, not authorization calls. Production activation is expressly outside this leaf. |
| No SQL mutation, HTTP/queue/assessment/scope-policy change | No source changes this round. Import search shows only the codec and Vulture whitelist import identity contracts; no production caller imports the codec. |
| Focused tests, ruff, mypy and inventory | Passed as recorded above; no test additions, therefore no new inventory note required. |
| Required integration CI, reachability/disposition and promotion policy | Provenance wrapper FAILS the two reachability gates; its promotion check passes. Full integration CI and reported merge-queue `test: failure` attribution remain UNVERIFIED. |

## Handoff

**BLOCKED.** Only this report changed. No evidence supports a code repair or a Vulture amendment. Prior unauthorized reachability baseline/disposition changes are preserved, not silently approved or discarded. The reproduced blocker is at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`; resolving it requires protected-base policy coordination outside this writer's authorization, not a candidate grant or cosmetic import. The issue's no-activation/no-ledger constraints remain binding.

The assigned `test: failure` is not reproduced by the four focused files or adjacent tasks/runs suites; a failing-node log tied to the evaluated SHA is still needed to attribute and repair that check. Do not treat this documentation-only checkpoint as implementation completion or merge approval. No new mutation/pre-fix failure evidence exists because no code/test repair was made. No database session/row-count evidence was produced.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 blocking provenance command. Next: campaign owner resolves trusted-base reachability policy and supplies the actual failing test log; rerun mandatory disposable-PG and integration validation on the resulting coordinated head.
