# Issue 1893 bounded CI repair — 930426bc

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `fd5f55c232fe00fb3c32656074f5c5e7cc8e590b`; supplied develop base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- One item: issue #1893 CI repair. Inspect the supplied dispatch snapshot and five driver check logs, existing admission codec/identity tests, relevant ADRs, and CI gate definitions. Do not re-enumerate GitHub issues or PRs.
- Candidate implementation files are `packages/maistro-core/src/maistro/tasks/admission_codec.py`, adjacent `runs/admission_identity.py`, and their existing package tests. Change only if executed evidence identifies a defect. The only permitted ledger amendment is `quality/vulture-baseline.json`, if the exact prescribed scanner identifies reviewed retained identities.
- Initial worktree is clean and HEAD matches dispatch. No salvage required.
- Ambiguity: reported `test: failure` has no failing test identity in the prompt. Inspect supplied evidence and reproduce focused tests before proposing a repair.
- Earlier validation claims are historical evidence, not results of this run. Production activation and ownership/policy choices remain outside this repair.

## Results

- Driver logs read: sync/lint/format pass, focused driver tests 324 passed / 3 skipped, suite inventory 16,543 nodes passes. They do not contain a failing-test traceback.
- Exact prescribed Vulture scan executed: exit 0 (`/tmp/1893-930426bc-vulture.log`); no ledger amendment justified.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`: exit 1 (`/tmp/1893-930426bc-provenance.log`), details under review.
- Verified local `origin/develop` resolves to the supplied base. Merge base is `2154f845347c9541016288c760f8da3f5cd2e064`. No merge conflict exists in the assigned worktree; the prior block is a provenance/authorization block, not a sync conflict.
- Read codec and all adjacent codec tests: encoder already supplies both binding columns; PG tests exercise real TEXT reads but synthetic identity fixtures, not authorized production admission. No production defect established yet.
- Provenance failure is confirmed: both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` have unauthorized new unreachable-module and disposition entries (log lines 20–29). Vulture has 1,322 reviewed identities / 1,322 findings; this is not a Vulture debt mismatch.
- Independently executed `uv run ruff check .` and `uv run ruff format --check .`: pass (3,301 files). Scoped mypy on the two production modules: pass.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: 201 passed / 3 skipped; skipped PG legs are not durability evidence.
- Local PostgreSQL reports 18.6; disposable database name `maistro_1893_930426bc` confirmed absent before creation.

- `createdb maistro_1893_930426bc` and `DATABASE_URL=postgresql:///maistro_1893_930426bc uv run alembic upgrade head`: pass, migrated real chain to **063** (not the historical notes' 061).
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to `postgresql:///maistro_1893_930426bc`, plus `MAISTRO_REQUIRE_PG_LEGS=1`, the same focused pytest command with `-o junit_family=legacy --junitxml=/tmp/1893-930426bc-focused.xml`: **204 passed, zero skipped**. Unbound/bound/acknowledged pool pairs: **2052100/2052102**, **2052103/2052107**, **2052108/2052109**, each same database via local socket, different backend PID, one persisted scoped row. Tests restore/delete their inserted rows.
- Post-test SQL confirms revision 063 and **0 admission rows / 0 generation identities / 0 Run identities**. An initial additional query used nonexistent `runs` and failed (exit 1); schema discovery identifies `canonical_runs`, `canonical_node_runs`, and `canonical_attempts` for the corrected check. This was a validation-query error, not a product failure.
- Adjacent `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1,919 passed / 310 skipped / 6 warnings**, exit 0 (log `/tmp/1893-930426bc-adjacent.log`; PG variables not set for this broader run). Warnings are aiosqlite worker-thread `Event loop is closed` during existing SQLite-store tests; not claimed resolved.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` and `uv run python scripts/check-shipped-surface-truth.py`: exit 0.
- Source import search finds only the codec-to-DTO import and Vulture whitelist; no runtime admission consumer. Snapshot check metadata did not yield a current-head failing `test` traceback. Reported `test: failure` remains **UNRESOLVED**, not repaired or disproven by scoped success.

## Architectural reconciliation

Read accepted ADR-081226-a66b (canonical execution hierarchy), ADR-082826-b601 (one consumer, explicit eligibility), and ADR-083126-5e62 (candidate evidence is not authorization). Do not add a fake import or activate a consumer to evade reachability; do not amend reachability policy in this Vulture-only exception. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. The codec is staged representation, not an independent execution/admission authority.

## Acceptance evidence and limits

All results above execute starting source SHA `fd5f55c232fe00fb3c32656074f5c5e7cc8e590b`; this round changes only this report. No new tests, inventory delta, source changes, gate changes, or ledger amendments.

| Criterion | Evidence |
| --- | --- |
| Frozen/slotted header, exact interfaces, strict format/schema/scalar decoding | Source inspection plus focused header/schema cases passed. |
| Header survives full decode failure; no clock, incoming fingerprint, or assessment | Focused expiry/fingerprint preservation and mismatch cases passed; codec source is mapping-to-DTO only. |
| Immutable V2 storage mapping, UUID hex only at storage, paired binding | Focused unbound/bound/acknowledged round trips passed against migrated PG. An in-memory-only wrapper omitting `task_id` caused the existing bound-round-trip test to fail at `test_admission_codec.py:134`; no source mutation. |
| Legacy unresolved/bound/partial distinctions without fabricated identities | Focused legacy pair, receipt-only, missing receipt, unreadable/whitespace and completed-at cases passed. |
| Strict snapshots and safe typed errors | Duplicate keys, roots, bare nonfinite, overflowing/lossy numbers, excessive nesting and surrogate tests passed; PG corruption injection checks all three TEXT snapshots through both pools. |
| Tagged evidence and fingerprint preservation | Focused tagged-token and Unicode/numeric round trips passed. These retain tag dictionaries; they do **not** prove `model_of`/`model_of_json` materialization of real request/receipt/Run models. |
| Real raw/production pool equivalence | Three non-skipped live PG cases above, distinct sessions, same database, one row per case. Corrected final SQL: **0 canonical Runs / 0 NodeRuns / 0 Attempts**. |
| Reachable admission with explicit authorized principals, Workspace/Project, registered Graph | **UNVERIFIED**. Fixtures use synthetic strings, and the codec has no production consumer. No authority inferred from fixture DTO construction. |
| Run JSONB object INSERT via production serialization | **UNVERIFIED** by these TEXT-only tests. |
| Required integration CI and reported `test: failure` repaired | **UNVERIFIED**; scoped tests pass but do not reproduce the full multi-package CI job. No failing current-head test traceback supplied. |
| Applicable quality checks | Ruff, format, scoped mypy, exact Vulture, shipped-surface and package inventory pass. Trusted-base provenance fails on two unauthorized admission modules/dispositions. |
| No policy/activation/queue/HTTP change | Only this evidence report changed; no competing execution or authorization path added. |

## Handoff

**BLOCKED.** The Vulture exception cannot authorize a reachability/disposition grant. Integration owner must resolve coordinated staging/trusted-base authorization under the two-merge rule, then supply the exact failing CI SHA/step/traceback if `test: failure` persists. Do not repeat this repair on unchanged evidence or claim independent merge readiness.

Disposable database `maistro_1893_930426bc` remains available for inspection; no application rows remain in the checked tables. Validation logs/JUnit are under `/tmp/1893-930426bc-*`. No destructive migration/downgrade tests were run. Progress: checked 1 issue, done 0 repairs, skipped 0, errors 1 blocking provenance gate; next is owner coordination and failing-CI evidence, not speculative code edits.
