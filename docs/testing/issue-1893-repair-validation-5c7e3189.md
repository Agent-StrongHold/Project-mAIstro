# Issue #1893 repair validation

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `6d1c67e39db0cd5eaf2ba92a9d13b70c33c13e24`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Single item: #1893 immutable admission codec; repair only evidenced failures.
- Inspect codec/identity implementation, adjacent tests, applicable ADRs, existing inventory notes and CI gate definitions. No production activation or other issue work; no gate/grant/reachability-ledger edits.
- Inputs frozen to job `5c7e3189da3e4e7b805962942d9b39f7` dispatch snapshot and check logs, plus supplied prior result. No remote enumeration.
- Initial worktree clean; exact starting HEAD confirmed.

## Initial evidence and ambiguity

Driver logs: dependency sync, Ruff check/format and suite inventory passed; focused tests 201 passed, 3 skipped. Prior result reports trusted-base reachability authorization failure. The generic `test: failure` contains no current-head failure trace; do not assume the earlier result or diagnosis remains true. Proceed by inspecting captured CI evidence and executing focused tests/gates. PostgreSQL skips are not durability evidence.

## Results

- Executed CI-exact Vulture scan (`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`): exit 0. No speculative ledger amendment.
- Executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1; full output in job `worker-provenance.log`. This resolved SHA equals local `origin/develop`; no missing or guessed ref used.
- Read codec and adjacent tests: bindings already emitted together; codec explicitly has no production consumer. Do not add fake reachability or activation to repair a provenance gate.

- Focused local pytest (`packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`): 201 passed, 3 PostgreSQL cases skipped (1.29s), `worker-focused.log`.
- Provenance log confirms only four admission findings: both new modules and both new dispositions lack trusted-base authorization (169 -> 171). Vulture: 1323 findings/1323 reviewed, zero unclassified.
- Production-source search finds only the codec's identity import and the Vulture whitelist; no codec consumer. DTO construction is not authorized admission.
- Reviewed accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082826-b601 and ADR-083126-5e62: preserve the canonical lifecycle, immutable admission facts, opt-in canonical consumer and trusted-base authority. No candidate-side authorization or fake caller is an acceptable reconciliation.
- First captured-CI extraction found no top-level `check_runs` objects; captured evidence shape needs one bounded follow-up. Generic reported test failure remains UNRESOLVED, not justification for a guessed patch.

- Bounded captured-CI follow-up: snapshots are lists. `test` failed at `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (other linked PR); it succeeded at candidate PR snapshot `fcc8b437f209a35aa68a61d6f0a5387414938355`, where `exact-debt-ledger` failed. No current assigned-head test failure trace supplied. Full extraction: `worker-captured-ci.txt`. Attribution of generic failure remains UNRESOLVED; no further remote investigation.
- Locally executed Ruff check/format: PASS, 3277 files formatted. Targeted mypy on codec and identity modules: PASS (2 files).
- Candidate gates: reachability PASS (1396 modules, 171 unreachable); dispositions PASS (50 groups, 171 modules); shipped-surface truth PASS; suite inventory PASS (16466 nodes, no duplicate evidence). Logs `worker-{reachability,dispositions,surface,inventory}.log`.
- Created a fresh disposable database `admission_1893_5c7e3189` in existing lane container `auto-1893-pg` (PostgreSQL 18.6). First `DATABASE_URL=postgresql://postgres@127.0.0.1:15498/admission_1893_5c7e3189 uv run alembic upgrade head` failed before migration: password required. Will use the container's configured credential without printing or committing it. No existing database is modified.

- Authenticated migration succeeded through the real chain 001 -> 062, including 055. Credential loaded privately from the lane container's configuration; `worker-migration-authenticated.log`.
- With nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL` pointing at that same fresh database and `MAISTRO_REQUIRE_PG_LEGS=1`, ran `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml`: **204 passed, zero skipped**, 1.68s. Each PG case persists exactly one scoped admission row and contrasts raw/production-codec sessions. This is storage/DTO evidence, not canonical admission authorization.
- Direct final SQL: revision 062; admission rows/distinct generations/distinct Run IDs all 0; canonical Run/NodeRun/Attempt counts all 0. Read live `ck_task_idempotency_v2_identity`: binding columns must occur together and task_id must equal receipt_id. `worker-sql.log`.
- Negative probe: replaced the encoder in memory only with a wrapper setting `task_id=None`, then ran the existing round-trip test. Bound and acknowledged cases failed at `test_admission_codec.py:134`; unbound passed. No disk source edits. `worker-binding-mutation.log`: 2 failed, 1 passed, 128 deselected. The existing test independently catches the historical binding defect.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped, 5 warnings**, 50.08s; PostgreSQL was not enabled for this broader run. Warnings report aiosqlite worker threads on closed event loops, not codec failures (`worker-adjacent.log`).
- JUnit production/raw session PID pairs: 36923/36924 (unbound), 36925/36926 (bound), 36927/36928 (acknowledged). All identify `admission_1893_5c7e3189`, server `172.17.0.9/32:5432`; each case records one persisted row. All 204 node IDs are retained in `worker-focused-pg.xml`.
- Historical `issue-1893-repair-validation.md` was initially mistaken for a new report path. Before finalization, this round was preserved at this job-specific path and the complete historical report reconstructed byte-for-byte from HEAD. No prior report content is removed in the final diff.

## Acceptance map

All named tests below executed in the **204 passed / zero skipped** run at the exact starting source SHA. These prove the codec boundary, not reachable production admission.

| Criterion | Executed evidence |
| --- | --- |
| Immutable v2 snapshots, binding storage shape, fresh SQL mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping`; binding mutation fails independently at line 134 |
| Owner token strict storage-only UUID hex | `test_owner_token_is_hex_at_storage_only`, strict-generation tests; identity repr tests |
| Bound/unbound/partial legacy evidence without invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only and bound-without-receipt rejection tests |
| Expired supported header preserves scalars without a clock | `test_expired_legacy_header_does_not_invent_missing_identity` |
| Header expiry remains available despite corrupt snapshot | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header fingerprint remains available despite partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown format cannot become legacy; row/header agreement and signed timestamps | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, scalar mismatch and invalid scalar header tests |
| Tagged nonfinite nested evidence survives; no fingerprint recalculation | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`; valid numeric/Unicode cases |
| Invalid/duplicate/nonobject/bare nonfinite JSON rejects safely | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting/lossy number/non-UTF8 safe-failure tests; corrupt surrogate TEXT injected through both real pools |
| Raw/production pool independence on migrated TEXT columns | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (3 live PG states), same DB and distinct sessions above |
| Required frozen/slotted header, six enum codes, validated error scope, typed constructor use, named-column SQL mapping | Source inspection of codec plus header/error/fresh mapping tests; targeted mypy passed |
| Representation only: no SQL mutation, HTTP mapping, clock, classifier, queue/claim/policy change | Source inspection: codec only translates mappings/DTOs. No source or runtime activation change in this round |
| Common local quality validation | Ruff, format, mypy, inventory, Vulture, candidate reachability/dispositions and shipped-surface gates passed; trusted-base provenance **FAILED** |

**UNVERIFIED:** real authorized principals/Workspace/Project/registered Graph admission; new snapshots encoded from actual models with evidence-json and materialized using `model_of`/`model_of_json`; original-model fingerprinting; Run `json_of(run)` TEXT-to-JSONB object insertion; reachable consumer expiry/409 ordering (C/F2, not B2); full unchanged required integration CI; coordination/activation approval. No downgrade behavior was tested. The tests use synthetic identities and directly insert admission rows, so they establish none of these runtime properties.

## Handoff

**BLOCKED.** No evidenced codec defect or unbanked Vulture identity warrants an implementation/ledger patch. The reproduced provenance failure is at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`, outside the permitted Vulture exception. Owner-authorized resolution consistent with the trusted-base two-merge rule must precede another integration attempt; candidate self-authorization, fake imports or activation are not repairs. Obtain the exact current-head `test` traceback before assigning another speculative test fix.

Only this job-specific report changes. No source, tests, inventory counts, ledger, grants or gates change; no inventory-delta note is needed. The fresh disposable DB is retained for inspection. Local documentation commit is a blocked evidence handoff, never integration approval.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 unresolved provenance blocker. Next: integration-owner provenance resolution and current-head failing CI evidence.
