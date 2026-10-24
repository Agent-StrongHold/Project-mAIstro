# Issue 1893 repair checkpoint

## Frozen scope

Only issue #1893, branch auto-1893, starting HEAD a7c1aa48e5031a6615c2186fe925e030619ac02c; supplied develop base ac69535ef165ded3ca82cd3428728569de3251fa. Process the existing merge and its sole conflict in packages/maistro-core/tests/extensions/test_pack_contracts.py, relevant admission tests/ADRs, and evidence/inventory notes. No new GitHub enumeration or mutations.

## Incoming state / evidence

- HEAD matches assignment. MERGE_HEAD resolves exactly to supplied develop base ac69535ef165ded3ca82cd3428728569de3251fa (canonical Goal store #1938).
- Existing staged changes are incoming develop merge content, not a new implementation scope. Preserve them.
- Backups: ../incoming-1893.patch, ../incoming-1893-index.patch, ../incoming-1893-status.txt.
- Driver check-1.log and check-2.log fail parsing conflict markers at test_pack_contracts.py:874; check-3.log pytest collection fails there; check-4.log suite inventory fails collection there. check-0.log dependency sync succeeded.
- Assumption: finish the already-started merge of the exact supplied develop snapshot; no fetch is necessary to resolve this pinned merge. Preserve both collision regression tests with their markers and assertions.

Adjacent production inspection found the clean auto-merge also duplicated the identical active-extension collision condition in packs.py:1270 and :1277; the second branch is unreachable. Resolve that merge artifact by retaining develop's existing guard and both parents' regression tests. This is part of the same merge repair, not new feature scope. Prior result.json reports BLOCKED, not integration approval. Codec explicitly states no production consumer yet; do not activate it to bypass provenance.

## Executed repair validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3292 files.
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -r s`: 312 passed, 3 skipped (315 nodes). PostgreSQL cases skip for missing both required DSNs at codec test line 470; not durability proof.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16540 nodes, no duplicates. Zero new delta beyond both parents' existing notes.
- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed / 1323 findings, no unclassified identities. No ledger amendment justified.
- Scoped mypy on admission_codec.py and admission_identity.py: PASS (2 files).
- Conflict resolved and staged; no unmerged paths remain. Working diff whitespace check passed; cached whitespace check flags two inherited develop docs (goal-1572-repair-20261012-round59.md:47 trailing space, issue-1572-repair-checkpoint.md:191 blank EOF). These are outside repair scope and preserved unchanged.

Validation used 1800-second timeouts. Merge committed as ac3c1a942b7df919abe4bf1f1a966b3edbfba9c1; worktree clean immediately afterwards. No authority, gate, or ledger changes made by this repair.

## Post-merge evidence

- `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Trusted base now correctly resolves to ac69535ef165. Both admission modules still introduce unauthorized unreachable identities and dispositions (169 -> 171). All other aggregator sub-gates pass. The develop sync does NOT resolve this authority blocker.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: PASS, 15467 passed, 1070 skipped, 3 xfailed, 53 warnings in 241.17s; 16540 collected nodes. Raw output: /tmp/1893-9c47-core.log. Warnings include aiosqlite thread shutdown and unawaited fake subprocess coroutine warnings; no test failure. Skips are not counted as acceptance proof.

- Post-merge CI-exact Vulture: PASS again against the supplied develop base, 1323 / 1323. Reachability scan: PASS as candidate bookkeeping (1403 modules / 171 unreachable); dispositions: PASS, 50 groups; shipped-surface and promotion-surface: PASS. These do not supersede the failing trusted-base gate.
- In-memory mutation control: replacing the sole active-extension guard condition with `False` made BOTH preserved collision tests fail with `DID NOT RAISE PackIdentityConflict` at test lines 884 and 903 (2 failed, 109 deselected). No source file was modified for this control. Fresh unmutated run: 2 passed, 109 deselected.
- `uv run python scripts/check-merge-markers.py`: PASS, no conflict markers. CI workflows and Vulture ledger are byte-identical to the supplied develop base; incoming workflow changes were preserved, not edited as a repair.

## Acceptance audit / architectural reconciliation

Read repository instructions and accepted ADR-062 (including its retired executor caveat), ADR-081226-a66b (canonical Run/NodeRun/Attempt), ADR-082526-7f02 (immutable admission provenance, Attempt dispatch identity), ADR-082526-1899 (real readers rather than manufactured roots), and ADR-083126-5e62 (trusted-base authority). No new scheduler, Goal store, execution, event or authorization path. The incoming canonical Goal-store merge is preserved without reimplementation. No conflict with these ADRs requires behavioral changes in B2.

| Issue criterion | Fresh evidence / limit |
| --- | --- |
| Six interfaces, frozen/slotted validated header, enum codes, fresh flat mapping | Source inspection plus passing focused codec/identity suites; named storage columns and constructor validation, no column-order decoding. |
| v2 snapshots and strict UUID hex, task/run/receipt consistency | Passing three-state round trips, token tests, generation rejection, binding mismatch and acknowledgement tests. Independent storage-shape assertions at codec tests:134-137. |
| No identity guessing for legacy unbound/bound/partial/receipt-only | Passing legacy tests including unreadable/whitespace values, bound pair without receipt, and completed_at ignored. A pair without receipt remains partial because the prerequisite binding DTO requires receipt identity; fabricating it is forbidden. |
| Header separation, scalar timestamps/hash validation, mismatched header and unknown format fail closed | Passing expiry/fingerprint-preservation, invalid scalars, unknown-format and mismatch tests. Header decoder takes neither clock nor incoming fingerprint. Consumer expiry/409 ordering is not B2 behavior and is not claimed. |
| Strict JSON, error hygiene, tags and stored fingerprint unchanged | Passing invalid/duplicate/nonobject/bare-nonfinite, nesting, lossy-number, Unicode and suppressed-chain tests. Snapshot/text/owner values are absent from error messages. Tagged fixtures prove preservation, not actual model materialization. |
| Existing evidence-json encoding, model_of/model_of_json, original-model fingerprinting and arbitrary permitted program_context end-to-end | UNVERIFIED: tests use handwritten tags and fixed fingerprints. No consumer is activated. |
| Real migrated PostgreSQL, raw/production pools, Run JSONB object shape, session and final row counts | UNVERIFIED: three pool cases skipped for missing DSNs. No database created/migrated, no SQL cleanup counts or transaction/durability claim this round. Positive authorized Workspace/Project/registered Graph admission is not established by placeholder DTO identities. |
| Production reachability | Absent: import search finds codec-to-identity and whitelist only; codec:50-53 explicitly says no production consumer. Tests/re-exports are not runtime reachability. Wiring C or activating traffic is outside the leaf. |
| No clock/assessment/SQL mutation/live _assess/scope utility/HTTP/queue/deletion policy changes | Codec inspection and repair diff confirm no such changes. Only merge conflict resolution and evidence notes authored here. |
| Focused tests, inventory, Ruff/format, applicable mypy, CI Vulture/reachability/disposition/promotion | PASS as recorded above; full changed-package suite also passes. Mandatory trusted-base provenance FAILS. Full multi-package/frontend required CI is UNVERIFIED. |
| Coordination and activation release | UNVERIFIED; assignment permits local repair only, no integration or rollout approval. |

## Handoff

The actual driver collection failure is repaired and locally committed; mandatory provenance still prevents a MERGE-READY verdict. No candidate-side reachability grant or fake production wiring was added. The exact blocked identities remain `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`; completing the pinned develop merge did not authorize them. Owner action must reconcile the staged leaf with the no-baseline/grant constraint and trusted-base policy; do not repeat an unchanged-input repair or weaken the gate.

Authored/resolved files: `packages/maistro-core/tests/extensions/test_pack_contracts.py`, `packages/maistro-core/src/maistro/extensions/packs.py`, `docs/testing/inventory-notes/atomic-admission-b2-merge-9c47bc40.md`, and this report. All other merge files are preserved incoming develop content. Backups remain outside the worktree as named above.

Progress: checked 1, done 1 (merge/test repair), skipped 0, errors 1 (remaining provenance blocker). Verdict: BLOCKED, not integration approval. Next: owner-approved trusted-base/consumer reconciliation and fresh real-database/full-CI evidence.
